import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db/prisma";
import OpenAI from "openai";

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

const MODEL = process.env.OPENAI_MODEL || "gpt-4o";

export const maxDuration = 300; // 5 минут для обработки множества документов

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const body = await request.json();
    const { reviewId, columnId } = body;

    if (!reviewId) {
      return NextResponse.json(
        { error: "reviewId обязателен" },
        { status: 400 }
      );
    }

    // Получаем таблицу и проверяем права
    const review = await prisma.tabularReview.findFirst({
      where: {
        id: reviewId,
        userId: session.user.id,
      },
      include: {
        columns: true,
      },
    });

    if (!review) {
      return NextResponse.json(
        { error: "Таблица не найдена" },
        { status: 404 }
      );
    }

    // Определяем какие колонки обрабатывать
    const columnsToProcess = columnId
      ? review.columns.filter((c) => c.id === columnId)
      : review.columns;

    if (columnsToProcess.length === 0) {
      return NextResponse.json(
        { error: "Нет колонок для обработки" },
        { status: 400 }
      );
    }

    // Получаем документы
    const documents = await prisma.document.findMany({
      where: {
        id: { in: review.documentIds },
        userId: session.user.id,
      },
    });

    const useMocks = !process.env.OPENAI_API_KEY;
    const results = [];

    // Обрабатываем каждую колонку
    for (const column of columnsToProcess) {
      // Обрабатываем каждый документ
      for (const document of documents) {
        try {
          let value: string;
          let citation: any = null;
          let confidence: number = 1.0;

          if (useMocks) {
            // Мок-реализация
            value = `Мок-значение для "${column.query}" из ${document.filename}`;
            citation = {
              documentId: document.id,
              filename: document.filename,
              position: 0,
            };
          } else {
            // Реальная обработка через OpenAI
            const prompt = `Ты - эксперт по извлечению данных из юридических документов.

Задача: Извлеки информацию из следующего документа по запросу: "${column.query}"

Документ:
${document.content.substring(0, 8000)}

Верни ответ в формате JSON:
{
  "value": "извлеченное значение",
  "citation": {
    "text": "цитата из документа",
    "position": позиция_в_документе
  },
  "confidence": число_от_0_до_1
}`;

            const completion = await openai.chat.completions.create({
              model: MODEL,
              messages: [
                {
                  role: "system",
                  content: "Ты - эксперт по извлечению данных. Всегда отвечай валидным JSON.",
                },
                {
                  role: "user",
                  content: prompt,
                },
              ],
              response_format: { type: "json_object" },
              temperature: 0.2,
            });

            const result = JSON.parse(completion.choices[0].message.content || "{}");
            value = result.value || "";
            citation = {
              documentId: document.id,
              filename: document.filename,
              text: result.citation?.text || "",
              position: result.citation?.position || 0,
            };
            confidence = result.confidence || 0.5;
          }

          // Сохраняем или обновляем ячейку
          await prisma.tabularCell.upsert({
            where: {
              reviewId_columnId_documentId: {
                reviewId: review.id,
                columnId: column.id,
                documentId: document.id,
              },
            },
            create: {
              reviewId: review.id,
              columnId: column.id,
              documentId: document.id,
              value,
              citation,
              confidence,
            },
            update: {
              value,
              citation,
              confidence,
              updatedAt: new Date(),
            },
          });

          results.push({
            columnId: column.id,
            documentId: document.id,
            success: true,
          });
        } catch (error) {
          console.error(
            `Ошибка при обработке документа ${document.id} для колонки ${column.id}:`,
            error
          );
          results.push({
            columnId: column.id,
            documentId: document.id,
            success: false,
            error: error instanceof Error ? error.message : "Неизвестная ошибка",
          });
        }
      }
    }

    return NextResponse.json({
      success: true,
      processed: results.filter((r) => r.success).length,
      failed: results.filter((r) => !r.success).length,
      results,
    });
  } catch (error) {
    console.error("Ошибка при обработке таблицы:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при обработке таблицы",
      },
      { status: 500 }
    );
  }
}

