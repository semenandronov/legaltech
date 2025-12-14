import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db/prisma";

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const body = await request.json();
    const { reviewId, title, query, dataType } = body;

    if (!reviewId || !title || !query) {
      return NextResponse.json(
        { error: "reviewId, title и query обязательны" },
        { status: 400 }
      );
    }

    // Проверяем права доступа
    const review = await prisma.tabularReview.findFirst({
      where: {
        id: reviewId,
        userId: session.user.id,
      },
    });

    if (!review) {
      return NextResponse.json(
        { error: "Таблица не найдена" },
        { status: 404 }
      );
    }

    // Получаем текущее количество колонок для определения порядка
    const columnCount = await prisma.tabularColumn.count({
      where: { reviewId },
    });

    const column = await prisma.tabularColumn.create({
      data: {
        reviewId,
        title,
        query,
        dataType: dataType || "text",
        order: columnCount,
      },
    });

    return NextResponse.json({ column });
  } catch (error) {
    console.error("Ошибка при добавлении колонки:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при добавлении колонки",
      },
      { status: 500 }
    );
  }
}

