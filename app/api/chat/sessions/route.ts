import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db/prisma";

export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const sessions = await prisma.chatSession.findMany({
      where: {
        userId: session.user.id,
      },
      include: {
        messages: {
          orderBy: { createdAt: "desc" },
          take: 1,
        },
        _count: {
          select: { messages: true },
        },
      },
      orderBy: {
        updatedAt: "desc",
      },
    });

    return NextResponse.json({ sessions });
  } catch (error) {
    console.error("Ошибка при получении сессий чата:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при получении сессий",
      },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const body = await request.json();
    const { title, documentIds } = body;

    const chatSession = await prisma.chatSession.create({
      data: {
        userId: session.user.id,
        title: title || "Новый чат",
        documentIds: documentIds || [],
      },
    });

    return NextResponse.json({ session: chatSession });
  } catch (error) {
    console.error("Ошибка при создании сессии чата:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при создании сессии",
      },
      { status: 500 }
    );
  }
}

