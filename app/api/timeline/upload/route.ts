import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db/prisma";
import { extractTextWithYandex } from "@/lib/yandex";
import { parseFile } from "@/lib/parsers";

export const maxDuration = 300; // 5 минут для обработки множества файлов

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
    const results = [];
    const useYandex = !!process.env.YANDEX_API_KEY;

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

        const buffer = Buffer.from(await file.arrayBuffer());
        let text = "";

        // Определяем, нужно ли использовать Yandex API
        const extension = file.name.split(".").pop()?.toLowerCase();
        const isImage = ["jpg", "jpeg", "png", "gif", "bmp", "tiff"].includes(extension || "");
        const isAudio = ["mp3", "wav", "ogg", "m4a", "flac"].includes(extension || "");
        const isVideo = ["mp4", "avi", "mov", "mkv", "webm"].includes(extension || "");

        if (useYandex && (isImage || isAudio || isVideo)) {
          // Используем Yandex API для изображений, аудио и видео
          try {
            text = await extractTextWithYandex(buffer, file.type, file.name);
          } catch (yandexError) {
            console.error(`Yandex API error for ${file.name}:`, yandexError);
            // Fallback на обычный парсер, если доступен
            if (!isImage && !isAudio && !isVideo) {
              const parseResult = await parseFile(buffer, file.type, file.name);
              text = parseResult.text;
            } else {
              throw yandexError;
            }
          }
        } else {
          // Используем обычные парсеры для PDF, DOCX, TXT
          const parseResult = await parseFile(buffer, file.type, file.name);
          text = parseResult.text;
        }

        if (!text || text.length < 50) {
          results.push({
            filename: file.name,
            success: false,
            error: "Не удалось извлечь текст из файла",
          });
          continue;
        }

        // Сохраняем документ
        const document = await prisma.document.create({
          data: {
            userId: session.user.id,
            filename: file.name,
            originalName: file.name,
            mimeType: file.type,
            size: file.size,
            content: text,
            metadata: {
              extractedWith: useYandex && (isImage || isAudio || isVideo) ? "yandex" : "local",
            },
          },
        });

        results.push({
          filename: file.name,
          success: true,
          documentId: document.id,
          textLength: text.length,
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
    console.error("Ошибка при загрузке документов для хронологии:", error);
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

