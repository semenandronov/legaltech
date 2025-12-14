import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { generateEmbedding } from "@/lib/ai";
import { prisma } from "@/lib/db/prisma";

export const maxDuration = 60;

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const body = await request.json();
    const { query, searchType = "KEYWORD", documentIds, limit = 20 } = body;

    if (!query || typeof query !== "string" || query.trim().length === 0) {
      return NextResponse.json(
        { error: "Поисковый запрос не может быть пустым" },
        { status: 400 }
      );
    }

    // Получаем документы пользователя
    const whereClause: any = {
      userId: session.user.id,
    };

    if (documentIds && Array.isArray(documentIds) && documentIds.length > 0) {
      whereClause.id = {
        in: documentIds,
      };
    }

    const documents = await prisma.document.findMany({
      where: whereClause,
      select: {
        id: true,
        filename: true,
        content: true,
      },
    });

    if (documents.length === 0) {
      return NextResponse.json({
        query,
        searchType,
        totalDocuments: 0,
        totalResults: 0,
        results: [],
        statistics: {
          documentsFound: 0,
          totalMatches: 0,
          averageMatchesPerDocument: 0,
        },
      });
    }

    const results: any[] = [];

    if (searchType === "KEYWORD" || searchType === "HYBRID") {
      // Текстовый поиск
      const queryLower = query.toLowerCase();
      const queryWords = queryLower.split(/\s+/).filter((w) => w.length > 2);

      for (const doc of documents) {
        const contentLower = doc.content.toLowerCase();
        const matches: string[] = [];
        const highlights: number[] = [];

        // Поиск точных совпадений
        if (contentLower.includes(queryLower)) {
          const index = contentLower.indexOf(queryLower);
          highlights.push(index);
          const start = Math.max(0, index - 100);
          const end = Math.min(doc.content.length, index + query.length + 100);
          matches.push(doc.content.substring(start, end));
        }

        // Поиск по отдельным словам
        for (const word of queryWords) {
          const regex = new RegExp(word, "gi");
          const wordMatches = doc.content.match(regex);
          if (wordMatches) {
            const firstMatch = doc.content.search(regex);
            if (!highlights.includes(firstMatch)) {
              highlights.push(firstMatch);
              const start = Math.max(0, firstMatch - 100);
              const end = Math.min(doc.content.length, firstMatch + word.length + 100);
              matches.push(doc.content.substring(start, end));
            }
          }
        }

        if (matches.length > 0) {
          // Вычисляем релевантность на основе количества совпадений
          const relevance = Math.min(1.0, matches.length / 10);

          results.push({
            documentId: doc.id,
            documentName: doc.filename,
            relevance,
            context: matches.slice(0, 5).join("... "),
            highlights: matches.length,
            matchType: "keyword",
          });
        }
      }
    }

    if (searchType === "SEMANTIC" || searchType === "HYBRID") {
      // Семантический поиск (векторный)
      // Генерируем embedding для запроса
      const queryEmbedding = await generateEmbedding(query);
      const queryVector = queryEmbedding.embedding;

      // Для каждого документа вычисляем косинусное сходство
      // В реальной реализации это делается через pgvector
      // Здесь используем упрощенный подход
      for (const doc of documents) {
        // Генерируем embedding для документа (или берем из БД)
        const docEmbedding = await generateEmbedding(doc.content.substring(0, 8000)); // Ограничиваем для скорости
        const docVector = docEmbedding.embedding;

        // Вычисляем косинусное сходство
        let dotProduct = 0;
        let queryMagnitude = 0;
        let docMagnitude = 0;

        for (let i = 0; i < queryVector.length; i++) {
          dotProduct += queryVector[i] * docVector[i];
          queryMagnitude += queryVector[i] * queryVector[i];
          docMagnitude += docVector[i] * docVector[i];
        }

        const similarity =
          dotProduct / (Math.sqrt(queryMagnitude) * Math.sqrt(docMagnitude));

        if (similarity > 0.3) {
          // Находим контекст вокруг наиболее релевантных частей
          const contextLength = 200;
          const contextStart = Math.floor(
            (doc.content.length * similarity) % (doc.content.length - contextLength)
          );
          const context = doc.content.substring(
            contextStart,
            contextStart + contextLength
          );

          const existingResult = results.find((r) => r.documentId === doc.id);
          if (existingResult) {
            // Объединяем с результатами текстового поиска
            existingResult.relevance = (existingResult.relevance + similarity) / 2;
            existingResult.semanticRelevance = similarity;
            existingResult.matchType = "hybrid";
          } else {
            results.push({
              documentId: doc.id,
              documentName: doc.filename,
              relevance: similarity,
              semanticRelevance: similarity,
              context,
              highlights: 1,
              matchType: "semantic",
            });
          }
        }
      }
    }

    // Сортируем по релевантности
    results.sort((a, b) => b.relevance - a.relevance);

    // Ограничиваем количество результатов
    const limitedResults = results.slice(0, limit);

    // Сохраняем запрос в БД
    const searchQuery = await prisma.searchQuery.create({
      data: {
        userId: session.user.id,
        query,
        searchType: searchType as any,
        filters: documentIds ? { documentIds } : null,
      },
    });

    // Сохраняем результаты
    await prisma.searchResult.createMany({
      data: limitedResults.map((result) => ({
        queryId: searchQuery.id,
        documentId: result.documentId,
        relevance: result.relevance,
        context: result.context,
        highlights: { count: result.highlights },
      })),
    });

    // Статистика
    const documentIdsFound = new Set(limitedResults.map((r) => r.documentId));
    const statistics = {
      documentsFound: documentIdsFound.size,
      totalMatches: limitedResults.reduce((sum, r) => sum + r.highlights, 0),
      averageMatchesPerDocument:
        documentIdsFound.size > 0
          ? limitedResults.reduce((sum, r) => sum + r.highlights, 0) /
            documentIdsFound.size
          : 0,
    };

    return NextResponse.json({
      query,
      searchType,
      totalDocuments: documents.length,
      totalResults: limitedResults.length,
      results: limitedResults,
      statistics,
    });
  } catch (error) {
    console.error("Ошибка при поиске:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при выполнении поиска",
      },
      { status: 500 }
    );
  }
}

