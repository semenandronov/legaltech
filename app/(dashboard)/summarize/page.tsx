"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { DocumentUploader } from "@/components/document-uploader/document-uploader";
import { SummaryResultComponent } from "@/components/summary-result/summary-result";
import { Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import type { SummaryResult, SummaryLength } from "@/lib/ai";

export default function SummarizePage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [textInput, setTextInput] = useState("");
  const [length, setLength] = useState<SummaryLength>("MEDIUM");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<SummaryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  if (!session) {
    router.push("/login");
    return null;
  }

  const handleFileSelect = (file: File | null, text: string) => {
    setSelectedFile(file);
    setTextInput(text);
    setResult(null);
    setError(null);
  };

  const handleSummarize = async () => {
    if (!selectedFile && !textInput.trim()) {
      setError("Пожалуйста, загрузите файл или вставьте текст");
      return;
    }

    setLoading(true);
    setProgress(0);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      if (selectedFile) {
        formData.append("file", selectedFile);
      } else {
        formData.append("text", textInput);
      }
      formData.append("length", length);

      const response = await fetch("/api/summarize", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка при создании резюме");
      }

      const data = await response.json();
      setResult(data);
      setProgress(100);
      toast({
        variant: "success",
        title: "Успешно",
        description: "Резюме создано",
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
        <h1 className="text-3xl font-bold">Суммирование документов</h1>
        <p className="text-muted-foreground mt-2">
          Создайте краткое резюме юридических документов и извлеките ключевые элементы
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Входные данные</CardTitle>
            <CardDescription>
              Загрузите файл или вставьте текст документа
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <DocumentUploader onFileSelect={handleFileSelect} />

            <div className="space-y-2">
              <Label htmlFor="length">Длина резюме</Label>
              <Select
                value={length}
                onValueChange={(value) => setLength(value as SummaryLength)}
              >
                <SelectTrigger id="length">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="SHORT">Короткое (2-3 предложения)</SelectItem>
                  <SelectItem value="MEDIUM">Среднее (5-7 предложений)</SelectItem>
                  <SelectItem value="DETAILED">Подробное (10-15 предложений)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <Button
              onClick={handleSummarize}
              disabled={loading || (!selectedFile && !textInput.trim())}
              className="w-full"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Обработка...
                </>
              ) : (
                "Получить резюме"
              )}
            </Button>

            {loading && (
              <div className="space-y-2">
                <Progress value={progress} />
                <p className="text-sm text-muted-foreground text-center">
                  Анализ документа...
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
            <CardDescription>Резюме и извлеченные элементы</CardDescription>
          </CardHeader>
          <CardContent>
            {result ? (
              <SummaryResultComponent result={result} />
            ) : (
              <div className="flex items-center justify-center h-64 text-muted-foreground">
                <p>Результаты появятся здесь после обработки документа</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

