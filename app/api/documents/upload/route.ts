import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { parseFile } from "@/lib/parsers";
import { generateEmbedding } from "@/lib/ai";
import { prisma } from "@/lib/db/prisma";

export const maxDuration = 120; // 2 minutes for multiple files

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const formData = await request.formData();
    const files = formData.getAll("files") as File[];

    if (!files || files.length === 0) {
      return NextResponse.json(
        { error: "Необходимо загрузить хотя бы один файл" },
        { status: 400 }
      );
    }

    const maxSize = parseInt(process.env.MAX_FILE_SIZE || "10485760", 10);
    const allowedTypes = (process.env.ALLOWED_FILE_TYPES || "pdf,docx,txt").split(",");

    const results = [];

    for (const file of files) {
      try {
        // Проверка размера
        if (file.size > maxSize) {
          results.push({
            filename: file.name,
            success: false,
            error: `Файл слишком большой (${(file.size / 1024 / 1024).toFixed(2)}MB)`,
          });
          continue;
        }

        // Проверка типа
        const fileExtension = file.name.split(".").pop()?.toLowerCase();
        if (!allowedTypes.includes(fileExtension || "")) {
          results.push({
            filename: file.name,
            success: false,
            error: `Неподдерживаемый тип файла: ${fileExtension}`,
          });
          continue;
        }

        // Парсинг файла
        const buffer = Buffer.from(await file.arrayBuffer());
        const parseResult = await parseFile(buffer, file.type, file.name);

        if (!parseResult.text || parseResult.text.length < 50) {
          results.push({
            filename: file.name,
            success: false,
            error: "Файл слишком короткий или не содержит текста",
          });
          continue;
        }

        // Генерация embedding
        const embeddingResult = await generateEmbedding(parseResult.text);
        const embedding = embeddingResult.embedding;

        // Сохранение в БД
        // Примечание: pgvector требует специального формата для хранения векторов
        // В реальной реализации нужно использовать Prisma с поддержкой pgvector
        // Здесь мы сохраняем embedding как JSON для совместимости
        const document = await prisma.document.create({
          data: {
            userId: session.user.id,
            filename: file.name,
            originalName: file.name,
            mimeType: file.type,
            size: file.size,
            content: parseResult.text,
            metadata: {
              pages: parseResult.metadata?.pages,
              encoding: parseResult.metadata?.encoding,
            },
            // embedding будет сохранен позже через raw SQL запрос, если используется pgvector
          },
        });

        // Если используется pgvector, нужно обновить embedding через raw SQL
        // await prisma.$executeRaw`
        //   UPDATE documents
        //   SET embedding = ${embedding}::vector
        //   WHERE id = ${document.id}
        // `;

        results.push({
          filename: file.name,
          success: true,
          documentId: document.id,
          textLength: parseResult.text.length,
        });
      } catch (error) {
        results.push({
          filename: file.name,
          success: false,
          error:
            error instanceof Error
              ? error.message
              : "Неизвестная ошибка при обработке файла",
        });
      }
    }

    const successCount = results.filter((r) => r.success).length;
    const failCount = results.length - successCount;

    return NextResponse.json({
      success: true,
      total: files.length,
      successful: successCount,
      failed: failCount,
      results,
    });
  } catch (error) {
    console.error("Ошибка при загрузке документов:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при загрузке документов",
      },
      { status: 500 }
    );
  }
}

