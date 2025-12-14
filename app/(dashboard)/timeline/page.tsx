"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { TimelineVisualization } from "@/components/timeline-visualization/timeline-visualization";
import { Loader2, Calendar } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

interface TimelineData {
  timelineId: string;
  title: string;
  events: any[];
  statistics: any;
}

export default function TimelinePage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<TimelineData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  if (!session) {
    router.push("/login");
    return null;
  }

  const handleCreateTimeline = async () => {
    if (!text.trim()) {
      setError("Пожалуйста, введите текст с событиями");
      return;
    }

    setLoading(true);
    setProgress(0);
    setError(null);
    setResult(null);

    try {
      const response = await fetch("/api/timeline/create", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text: text.trim(),
          title: title.trim() || undefined,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка при создании хронологии");
      }

      const data = await response.json();
      setResult(data);
      setProgress(100);
      toast({
        variant: "success",
        title: "Успешно",
        description: `Хронология создана: ${data.statistics.totalEvents} событий`,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Произошла ошибка";
      setError(errorMessage);
      setProgress(0);
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: errorMessage,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Хронология событий</h1>
        <p className="text-muted-foreground mt-2">
          Создайте упорядоченную временную шкалу событий из документов
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Входные данные</CardTitle>
            <CardDescription>
              Вставьте текст с датами и описанием событий
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="title">Название хронологии (необязательно)</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Например: Хронология дела №123"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="text">Текст с событиями</Label>
              <Textarea
                id="text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Вставьте текст с датами и событиями. Например:&#10;15 марта 2023 подписан контракт...&#10;20 апреля 2023 произведен платеж..."
                className="min-h-[400px]"
              />
              {text && (
                <p className="text-sm text-muted-foreground">
                  Символов: {text.length} | Слов: {text.split(/\s+/).filter(Boolean).length}
                </p>
              )}
            </div>

            <Button
              onClick={handleCreateTimeline}
              disabled={loading || !text.trim()}
              className="w-full"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Создание хронологии...
                </>
              ) : (
                <>
                  <Calendar className="mr-2 h-4 w-4" />
                  Создать хронологию
                </>
              )}
            </Button>

            {loading && (
              <div className="space-y-2">
                <Progress value={progress} />
                <p className="text-sm text-muted-foreground text-center">
                  Извлечение событий и дат...
                </p>
              </div>
            )}

            {error && (
              <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-md">
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Результат</CardTitle>
            <CardDescription>Визуализация временной шкалы</CardDescription>
          </CardHeader>
          <CardContent>
            {result ? (
              <TimelineVisualization data={result} />
            ) : (
              <div className="flex items-center justify-center h-64 text-muted-foreground">
                <p>Хронология появится здесь после обработки текста</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

