"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { EDiscoveryResults } from "@/components/ediscovery-results/ediscovery-results";
import { useDropzone } from "react-dropzone";
import { Upload, Search, FileText, X, Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

interface Document {
  id: string;
  filename: string;
  originalName: string;
  mimeType: string;
  size: number;
  createdAt: string;
}

export default function EDiscoveryPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [searchType, setSearchType] = useState<"KEYWORD" | "SEMANTIC" | "HYBRID">("KEYWORD");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [searchResults, setSearchResults] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  // Загрузка файлов
  const onDrop = async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      acceptedFiles.forEach((file) => {
        formData.append("files", file);
      });

      const response = await fetch("/api/documents/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка при загрузке файлов");
      }

      const data = await response.json();
      
      // Обновляем список документов
      const fetchResponse = await fetch("/api/documents");
      if (fetchResponse.ok) {
        const fetchData = await fetchResponse.json();
        setDocuments(fetchData.documents || []);
      }

      toast({
        variant: data.failed > 0 ? "destructive" : "success",
        title: data.failed > 0 ? "Частично успешно" : "Успешно",
        description: `Загружено: ${data.successful}, Ошибок: ${data.failed}`,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Ошибка при загрузке файлов";
      setError(errorMessage);
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: errorMessage,
      });
    } finally {
      setUploading(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "text/plain": [".txt"],
    },
    multiple: true,
  });

  // Загрузка списка документов
  useEffect(() => {
    if (!session) {
      router.push("/login");
      return;
    }
    const fetchDocuments = async () => {
      try {
        const response = await fetch("/api/documents");
        if (response.ok) {
          const data = await response.json();
          setDocuments(data.documents || []);
        }
      } catch (err) {
        console.error("Ошибка при загрузке документов:", err);
      }
    };
    if (session) {
      fetchDocuments();
    }
  }, [session, router]);

  // Выполнение поиска
  const handleSearch = async () => {
    if (!query.trim()) {
      setError("Введите поисковый запрос");
      return;
    }

    if (documents.length === 0) {
      setError("Сначала загрузите документы");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/ediscovery/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          searchType,
          documentIds: selectedDocuments.length > 0 ? selectedDocuments : undefined,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка при выполнении поиска");
      }

      const data = await response.json();
      setSearchResults(data);
      toast({
        variant: "success",
        title: "Поиск завершен",
        description: `Найдено: ${data.totalResults} результатов в ${data.statistics.documentsFound} документах`,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Ошибка при выполнении поиска";
      setError(errorMessage);
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: errorMessage,
      });
    } finally {
      setLoading(false);
    }
  };

  if (!session) {
    return null;
  }

  const toggleDocumentSelection = (documentId: string) => {
    setSelectedDocuments((prev) =>
      prev.includes(documentId)
        ? prev.filter((id) => id !== documentId)
        : [...prev, documentId]
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">E-Discovery</h1>
        <p className="text-muted-foreground mt-2">
          Быстрый поиск по множественным документам с использованием AI
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Панель управления */}
        <div className="lg:col-span-1 space-y-6">
          {/* Загрузка документов */}
          <Card>
            <CardHeader>
              <CardTitle>Загрузка документов</CardTitle>
              <CardDescription>
                Загрузите файлы для поиска (PDF, DOCX, TXT)
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
                  isDragActive
                    ? "border-primary bg-primary/5"
                    : "border-muted-foreground/25 hover:border-primary/50"
                }`}
              >
                <input {...getInputProps()} />
                <Upload className="h-8 w-8 mx-auto mb-2 text-muted-foreground" />
                {isDragActive ? (
                  <p className="text-sm">Отпустите файлы здесь...</p>
                ) : (
                  <>
                    <p className="text-sm mb-1">Перетащите файлы или нажмите</p>
                    <p className="text-xs text-muted-foreground">
                      Можно загрузить несколько файлов
                    </p>
                  </>
                )}
              </div>

              {uploading && (
                <div className="space-y-2">
                  <Progress value={undefined} />
                  <p className="text-sm text-muted-foreground text-center">
                    Загрузка и обработка файлов...
                  </p>
                </div>
              )}

              {documents.length > 0 && (
                <div className="space-y-2">
                  <Label>Загруженные документы ({documents.length})</Label>
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {documents.map((doc) => (
                      <div
                        key={doc.id}
                        className={`flex items-center gap-2 p-2 rounded border cursor-pointer transition-colors ${
                          selectedDocuments.includes(doc.id)
                            ? "bg-primary/10 border-primary"
                            : "hover:bg-muted"
                        }`}
                        onClick={() => toggleDocumentSelection(doc.id)}
                      >
                        <FileText className="h-4 w-4 flex-shrink-0" />
                        <span className="text-sm flex-1 truncate">{doc.originalName}</span>
                        {selectedDocuments.includes(doc.id) && (
                          <X className="h-4 w-4 text-primary" />
                        )}
                      </div>
                    ))}
                  </div>
                  {selectedDocuments.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Выбрано: {selectedDocuments.length} из {documents.length}
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Поиск */}
          <Card>
            <CardHeader>
              <CardTitle>Поиск</CardTitle>
              <CardDescription>Введите запрос для поиска</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="query">Поисковый запрос</Label>
                <Input
                  id="query"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Например: нарушение контракта"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleSearch();
                    }
                  }}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="search-type">Тип поиска</Label>
                <Select
                  value={searchType}
                  onValueChange={(value: any) => setSearchType(value)}
                >
                  <SelectTrigger id="search-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="KEYWORD">Текстовый поиск</SelectItem>
                    <SelectItem value="SEMANTIC">Семантический поиск</SelectItem>
                    <SelectItem value="HYBRID">Гибридный поиск</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button
                onClick={handleSearch}
                disabled={loading || !query.trim() || documents.length === 0}
                className="w-full"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Поиск...
                  </>
                ) : (
                  <>
                    <Search className="mr-2 h-4 w-4" />
                    Выполнить поиск
                  </>
                )}
              </Button>

              {error && (
                <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-md">
                  <p className="text-sm text-destructive">{error}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Результаты */}
        <div className="lg:col-span-2">
          <EDiscoveryResults data={searchResults} loading={loading} />
        </div>
      </div>
    </div>
  );
}

