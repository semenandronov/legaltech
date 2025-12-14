import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { parseFile } from "@/lib/parsers";
import { summarize, type SummaryLength } from "@/lib/ai";
import { prisma } from "@/lib/db/prisma";

export const maxDuration = 60; // 60 seconds

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const formData = await request.formData();
    const file = formData.get("file") as File | null;
    const text = formData.get("text") as string | null;
    const length = (formData.get("length") as SummaryLength) || "MEDIUM";

    if (!file && !text) {
      return NextResponse.json(
        { error: "Необходимо предоставить файл или текст" },
        { status: 400 }
      );
    }

    let documentText = "";

    if (file) {
      // Проверка размера файла
      const maxSize = parseInt(process.env.MAX_FILE_SIZE || "10485760", 10);
      if (file.size > maxSize) {
        return NextResponse.json(
          { error: `Файл слишком большой. Максимальный размер: ${maxSize / 1024 / 1024}MB` },
          { status: 400 }
        );
      }

      // Проверка типа файла
      const allowedTypes = (process.env.ALLOWED_FILE_TYPES || "pdf,docx,txt").split(",");
      const fileExtension = file.name.split(".").pop()?.toLowerCase();
      if (!allowedTypes.includes(fileExtension || "")) {
        return NextResponse.json(
          { error: `Неподдерживаемый тип файла. Разрешены: ${allowedTypes.join(", ")}` },
          { status: 400 }
        );
      }

      const buffer = Buffer.from(await file.arrayBuffer());
      const parseResult = await parseFile(buffer, file.type, file.name);
      documentText = parseResult.text;
    } else if (text) {
      documentText = text.trim();
    }

    if (!documentText || documentText.length < 50) {
      return NextResponse.json(
        { error: "Текст слишком короткий. Минимум 50 символов." },
        { status: 400 }
      );
    }

    // Вызов AI для суммирования
    const result = await summarize(documentText, length);

    // Сохранение в БД
    try {
      await prisma.summary.create({
        data: {
          userId: session.user.id,
          originalText: documentText,
          summary: result.summary,
          length,
          keyElements: result.keyElements as any,
        },
      });
    } catch (dbError) {
      console.error("Ошибка при сохранении в БД:", dbError);
      // Продолжаем, даже если не удалось сохранить
    }

    return NextResponse.json(result);
  } catch (error) {
    console.error("Ошибка при суммировании:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при обработке документа",
      },
      { status: 500 }
    );
  }
}

