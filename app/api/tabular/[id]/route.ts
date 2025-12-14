import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db/prisma";

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const review = await prisma.tabularReview.findFirst({
      where: {
        id: params.id,
        userId: session.user.id,
      },
      include: {
        columns: {
          orderBy: { order: "asc" },
        },
        cells: {
          include: {
            document: {
              select: {
                id: true,
                filename: true,
                originalName: true,
              },
            },
            column: true,
          },
        },
      },
    });

    if (!review) {
      return NextResponse.json(
        { error: "Таблица не найдена" },
        { status: 404 }
      );
    }

    return NextResponse.json({ review });
  } catch (error) {
    console.error("Ошибка при получении таблицы:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при получении таблицы",
      },
      { status: 500 }
    );
  }
}

