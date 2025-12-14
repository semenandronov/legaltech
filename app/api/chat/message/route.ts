import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/db/prisma";
import { generateChatResponse, mockGenerateChatResponse } from "@/lib/ai/chat";

export const maxDuration = 60;

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const body = await request.json();
    const { sessionId, message, documentIds } = body;

    if (!message || typeof message !== "string" || message.trim().length === 0) {
      return NextResponse.json(
        { error: "Сообщение не может быть пустым" },
        { status: 400 }
      );
    }

    // Получаем или создаем сессию чата
    let chatSession;
    if (sessionId) {
      chatSession = await prisma.chatSession.findFirst({
        where: {
          id: sessionId,
          userId: session.user.id,
        },
        include: {
          messages: {
            orderBy: { createdAt: "asc" },
            take: 20, // Последние 20 сообщений
          },
        },
      });
    }

    if (!chatSession) {
      chatSession = await prisma.chatSession.create({
        data: {
          userId: session.user.id,
          documentIds: documentIds || [],
          title: message.substring(0, 50),
        },
        include: {
          messages: {
            orderBy: { createdAt: "asc" },
          },
        },
      });
    }

    // Получаем документы для контекста
    const docIds = documentIds || chatSession.documentIds || [];
    const documents = await prisma.document.findMany({
      where: {
        id: { in: docIds },
        userId: session.user.id,
      },
      select: {
        id: true,
        filename: true,
        content: true,
      },
    });

    // Формируем контекст
    const context = {
      documents,
      history: chatSession.messages.map((msg) => ({
        role: msg.role as "user" | "assistant",
        content: msg.content,
      })),
    };

    // Сохраняем сообщение пользователя
    await prisma.chatMessage.create({
      data: {
        sessionId: chatSession.id,
        role: "user",
        content: message,
      },
    });

    // Генерируем ответ
    const useMocks = !process.env.OPENAI_API_KEY;
    const { response, citations } = useMocks
      ? await mockGenerateChatResponse(message, context)
      : await generateChatResponse(message, context, session.user.id);

    // Сохраняем ответ ассистента
    const assistantMessage = await prisma.chatMessage.create({
      data: {
        sessionId: chatSession.id,
        role: "assistant",
        content: response,
        citations: citations as any,
      },
    });

    // Обновляем время последнего обновления сессии
    await prisma.chatSession.update({
      where: { id: chatSession.id },
      data: { updatedAt: new Date() },
    });

    return NextResponse.json({
      sessionId: chatSession.id,
      message: {
        id: assistantMessage.id,
        role: "assistant",
        content: response,
        citations,
        createdAt: assistantMessage.createdAt,
      },
    });
  } catch (error) {
    console.error("Ошибка при обработке сообщения чата:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при обработке сообщения",
      },
      { status: 500 }
    );
  }
}

