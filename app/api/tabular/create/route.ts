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
    const { title, description, documentIds } = body;

    if (!title || typeof title !== "string") {
      return NextResponse.json(
        { error: "Название таблицы обязательно" },
        { status: 400 }
      );
    }

    if (!documentIds || !Array.isArray(documentIds) || documentIds.length === 0) {
      return NextResponse.json(
        { error: "Необходимо указать хотя бы один документ" },
        { status: 400 }
      );
    }

    // Проверяем, что документы принадлежат пользователю
    const documents = await prisma.document.findMany({
      where: {
        id: { in: documentIds },
        userId: session.user.id,
      },
    });

    if (documents.length !== documentIds.length) {
      return NextResponse.json(
        { error: "Некоторые документы не найдены или недоступны" },
        { status: 403 }
      );
    }

    const tabularReview = await prisma.tabularReview.create({
      data: {
        userId: session.user.id,
        title,
        description: description || null,
        documentIds,
      },
    });

    return NextResponse.json({ review: tabularReview });
  } catch (error) {
    console.error("Ошибка при создании таблицы:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при создании таблицы",
      },
      { status: 500 }
    );
  }
}

