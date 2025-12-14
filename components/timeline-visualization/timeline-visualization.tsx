"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { format, parseISO } from "date-fns";
import { ru } from "date-fns/locale";
import { Calendar, Clock, Download } from "lucide-react";
import { Button } from "@/components/ui/button";

interface TimelineEvent {
  id: string;
  date: string;
  description: string;
  eventType?: string | null;
  intervalDays?: number | null;
  order: number;
}

interface TimelineData {
  timelineId: string;
  title: string;
  events: TimelineEvent[];
  statistics: {
    totalEvents: number;
    dateRange: {
      start: string;
      end: string;
    };
    averageInterval: number;
  };
}

interface TimelineVisualizationProps {
  data: TimelineData | null;
}

export const TimelineVisualization = ({ data }: TimelineVisualizationProps) => {
  if (!data) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            <p>Хронология появится здесь после обработки текста</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const handleExport = () => {
    const content = `Хронология: ${data.title}\n\n${data.events
      .map((event, index) => {
        const date = format(parseISO(event.date), "dd.MM.yyyy", { locale: ru });
        const intervalDays = event.intervalDays;
        const interval =
          intervalDays !== null && intervalDays !== undefined
            ? `\n   └─ интервал: ${intervalDays} ${intervalDays === 1 ? "день" : intervalDays < 5 ? "дня" : "дней"}`
            : "";
        return `${date} ● ${event.description}${interval}`;
      })
      .join("\n\n")}\n\nСтатистика:\n• Всего событий: ${data.statistics.totalEvents}\n• Средний интервал: ${data.statistics.averageInterval.toFixed(1)} дней`;

    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `timeline-${data.timelineId}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>{data.title}</CardTitle>
              <CardDescription>
                Всего событий: {data.statistics.totalEvents} | Средний интервал:{" "}
                {data.statistics.averageInterval.toFixed(1)} дней
              </CardDescription>
            </div>
            <Button variant="outline" onClick={handleExport}>
              <Download className="mr-2 h-4 w-4" />
              Экспорт
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="relative">
            {/* Вертикальная линия */}
            <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-border" />

            {/* События */}
            <div className="space-y-6">
              {data.events.map((event, index) => {
                const date = parseISO(event.date);
                const formattedDate = format(date, "dd.MM.yyyy", { locale: ru });

                return (
                  <div key={event.id} className="relative pl-12">
                    {/* Точка на линии */}
                    <div className="absolute left-0 top-1.5">
                      <div className="h-3 w-3 rounded-full bg-primary border-2 border-background" />
                    </div>

                    {/* Содержимое события */}
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Calendar className="h-4 w-4 text-muted-foreground" />
                        <span className="font-semibold">{formattedDate}</span>
                        {event.eventType && (
                          <span className="text-xs px-2 py-0.5 rounded bg-secondary text-secondary-foreground">
                            {event.eventType}
                          </span>
                        )}
                      </div>
                      <p className="text-base">{event.description}</p>
                      {event.intervalDays !== null && event.intervalDays !== undefined && index > 0 && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          <span>
                            интервал: {event.intervalDays}{" "}
                            {event.intervalDays === 1
                              ? "день"
                              : event.intervalDays < 5
                              ? "дня"
                              : "дней"}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

