import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { extractTimelineEvents } from "@/lib/ai";
import { prisma } from "@/lib/db/prisma";

export const maxDuration = 60;

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user?.id) {
      return NextResponse.json({ error: "Не авторизован" }, { status: 401 });
    }

    const body = await request.json();
    const { text, title } = body;

    if (!text || typeof text !== "string" || text.trim().length === 0) {
      return NextResponse.json(
        { error: "Текст не может быть пустым" },
        { status: 400 }
      );
    }

    if (text.length < 50) {
      return NextResponse.json(
        { error: "Текст слишком короткий. Минимум 50 символов." },
        { status: 400 }
      );
    }

    // Извлечение событий
    const timelineResult = await extractTimelineEvents(text);

    if (timelineResult.events.length === 0) {
      return NextResponse.json(
        { error: "Не удалось извлечь события из текста" },
        { status: 400 }
      );
    }

    // Парсинг дат и расчет интервалов
    const eventsWithIntervals = timelineResult.events.map((event, index) => {
      let date: Date;
      try {
        // Парсим дату в формате ДД.ММ.ГГГГ
        const parts = event.date.split(/[.\-\/]/);
        if (parts.length === 3) {
          const day = parseInt(parts[0], 10);
          const month = parseInt(parts[1], 10) - 1;
          const year =
            parseInt(parts[2], 10) < 100
              ? 2000 + parseInt(parts[2], 10)
              : parseInt(parts[2], 10);
          date = new Date(year, month, day);
        } else {
          date = new Date(event.date);
        }
      } catch {
        date = new Date();
      }

      // Вычисляем интервал от предыдущего события
      let intervalDays: number | null = null;
      if (index > 0) {
        const prevEvent = eventsWithIntervals[index - 1];
        const prevDate = new Date(prevEvent.date);
        intervalDays = Math.floor(
          (date.getTime() - prevDate.getTime()) / (1000 * 60 * 60 * 24)
        );
      }

      return {
        ...event,
        date: date.toISOString(),
        intervalDays,
      };
    });

    // Сохранение в БД
    const timeline = await prisma.timeline.create({
      data: {
        userId: session.user.id,
        title: title || `Хронология от ${new Date().toLocaleDateString("ru-RU")}`,
        sourceText: text,
        events: {
          create: eventsWithIntervals.map((event, index) => ({
            date: new Date(event.date),
            description: event.description,
            eventType: event.eventType || null,
            order: index,
            intervalDays: event.intervalDays,
            metadata: event.eventType ? { type: event.eventType } : null,
          })),
        },
      },
      include: {
        events: {
          orderBy: {
            order: "asc",
          },
        },
      },
    });

    return NextResponse.json({
      timelineId: timeline.id,
      title: timeline.title,
      events: timeline.events.map((event) => ({
        id: event.id,
        date: event.date.toISOString(),
        description: event.description,
        eventType: event.eventType,
        intervalDays: event.intervalDays,
        order: event.order,
      })),
      statistics: {
        totalEvents: eventsWithIntervals.length,
        dateRange: {
          start: eventsWithIntervals[0].date,
          end: eventsWithIntervals[eventsWithIntervals.length - 1].date,
        },
        averageInterval:
          eventsWithIntervals
            .filter((e) => e.intervalDays !== null)
            .reduce((sum, e) => sum + (e.intervalDays || 0), 0) /
          (eventsWithIntervals.length - 1),
      },
    });
  } catch (error) {
    console.error("Ошибка при создании хронологии:", error);
    return NextResponse.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Произошла ошибка при создании хронологии",
      },
      { status: 500 }
    );
  }
}

