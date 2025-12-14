"use client";

import { useState, useEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { Loader2, Plus, Play, Download, Trash2, FileText, X, PlusCircle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import * as XLSX from "xlsx";

interface Document {
  id: string;
  filename: string;
  originalName: string;
}

interface TabularReview {
  id: string;
  title: string;
  description?: string;
  documentIds: string[];
  columns: Array<{
    id: string;
    title: string;
    query: string;
    order: number;
  }>;
  cells: Array<{
    id: string;
    columnId: string;
    documentId: string;
    value: string;
    citation?: any;
    confidence?: number;
    document: {
      id: string;
      filename: string;
      originalName: string;
    };
  }>;
}

export default function TabularPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const { toast } = useToast();
  const [reviews, setReviews] = useState<TabularReview[]>([]);
  const [selectedReview, setSelectedReview] = useState<TabularReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showAddColumnDialog, setShowAddColumnDialog] = useState(false);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [newReviewTitle, setNewReviewTitle] = useState("");
  const [newReviewDescription, setNewReviewDescription] = useState("");
  const [newColumnTitle, setNewColumnTitle] = useState("");
  const [newColumnQuery, setNewColumnQuery] = useState("");
  const [selectedCell, setSelectedCell] = useState<{
    documentId: string;
    columnId: string;
    value: string;
    citation?: any;
  } | null>(null);

  useEffect(() => {
    if (!session) {
      router.push("/login");
      return;
    }
    loadDocuments();
    loadReviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const loadReviews = async () => {
    try {
      const response = await fetch("/api/tabular");
      if (response.ok) {
        const data = await response.json();
        setReviews(data.reviews || []);
        if (data.reviews?.length > 0 && !selectedReview) {
          loadReview(data.reviews[0].id);
        }
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Не удалось загрузить таблицы",
      });
    }
  };

  if (!session) {
    return null;
  }

  const loadDocuments = async () => {
    try {
      const response = await fetch("/api/documents");
      if (response.ok) {
        const data = await response.json();
        setDocuments(data.documents || []);
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Не удалось загрузить документы",
      });
    }
  };

  const loadReview = async (id: string) => {
    try {
      const response = await fetch(`/api/tabular/${id}`);
      if (response.ok) {
        const data = await response.json();
        setSelectedReview(data.review);
      }
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Не удалось загрузить таблицу",
      });
    }
  };

  const handleCreateReview = async () => {
    if (!newReviewTitle.trim()) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Введите название таблицы",
      });
      return;
    }

    if (selectedDocuments.length === 0) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Выберите хотя бы один документ",
      });
      return;
    }

    setLoading(true);
    try {
      const response = await fetch("/api/tabular/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: newReviewTitle,
          description: newReviewDescription,
          documentIds: selectedDocuments,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка создания таблицы");
      }

      const data = await response.json();
      setSelectedReview(data.review);
      setShowCreateDialog(false);
      setNewReviewTitle("");
      setNewReviewDescription("");
      setSelectedDocuments([]);
      await loadReviews();
      toast({
        variant: "success",
        title: "Успешно",
        description: "Таблица создана",
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: error instanceof Error ? error.message : "Не удалось создать таблицу",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleAddColumn = async () => {
    if (!selectedReview) return;

    if (!newColumnTitle.trim() || !newColumnQuery.trim()) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Заполните все поля",
      });
      return;
    }

    setLoading(true);
    try {
      const response = await fetch("/api/tabular/add-column", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewId: selectedReview.id,
          title: newColumnTitle,
          query: newColumnQuery,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка добавления колонки");
      }

      const data = await response.json();
      await loadReview(selectedReview.id);
      setShowAddColumnDialog(false);
      setNewColumnTitle("");
      setNewColumnQuery("");
      toast({
        variant: "success",
        title: "Успешно",
        description: "Колонка добавлена",
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: error instanceof Error ? error.message : "Не удалось добавить колонку",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleProcess = async () => {
    if (!selectedReview) return;

    setProcessing(true);
    setProcessingProgress(0);

    try {
      const response = await fetch("/api/tabular/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewId: selectedReview.id,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка обработки");
      }

      const data = await response.json();
      
      // Имитация прогресса
      for (let i = 0; i <= 100; i += 10) {
        setProcessingProgress(i);
        await new Promise((resolve) => setTimeout(resolve, 200));
      }

      await loadReview(selectedReview.id);
      toast({
        variant: "success",
        title: "Успешно",
        description: `Обработано: ${data.processed}, Ошибок: ${data.failed}`,
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: error instanceof Error ? error.message : "Не удалось обработать таблицу",
      });
    } finally {
      setProcessing(false);
      setProcessingProgress(0);
    }
  };

  const handleExport = () => {
    if (!selectedReview) return;

    try {
      // Подготовка данных для экспорта
      const columns = selectedReview.columns.sort((a, b) => a.order - b.order);
      const documentsMap = new Map(
        selectedReview.documentIds.map((id) => {
          const doc = documents.find((d) => d.id === id);
          return [id, doc?.originalName || id];
        })
      );

      // Создание данных для таблицы
      const tableData: any[][] = [];
      
      // Заголовки
      tableData.push(["Документ", ...columns.map((col) => col.title)]);

      // Данные
      selectedReview.documentIds.forEach((docId) => {
        const row: any[] = [documentsMap.get(docId) || docId];
        columns.forEach((col) => {
          const cell = selectedReview.cells.find(
            (c) => c.documentId === docId && c.columnId === col.id
          );
          row.push(cell?.value || "");
        });
        tableData.push(row);
      });

      // Создание Excel файла
      const ws = XLSX.utils.aoa_to_sheet(tableData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Таблица");
      XLSX.writeFile(wb, `${selectedReview.title}.xlsx`);

      toast({
        variant: "success",
        title: "Успешно",
        description: "Таблица экспортирована",
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Не удалось экспортировать таблицу",
      });
    }
  };

  // Группировка ячеек по документам
  const getCellValue = (documentId: string, columnId: string) => {
    const cell = selectedReview?.cells.find(
      (c) => c.documentId === documentId && c.columnId === columnId
    );
    return cell;
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Табличный поиск</h1>
          <p className="text-muted-foreground mt-2">
            Автоматическое извлечение данных из документов в таблицу
          </p>
        </div>
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Создать таблицу
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>Создать новую таблицу</DialogTitle>
              <DialogDescription>
                Выберите документы и создайте таблицу для извлечения данных
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="title">Название таблицы *</Label>
                <Input
                  id="title"
                  value={newReviewTitle}
                  onChange={(e) => setNewReviewTitle(e.target.value)}
                  placeholder="Например: Анализ контрактов"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Описание</Label>
                <Textarea
                  id="description"
                  value={newReviewDescription}
                  onChange={(e) => setNewReviewDescription(e.target.value)}
                  placeholder="Описание таблицы (необязательно)"
                />
              </div>
              <div className="space-y-2">
                <Label>Документы *</Label>
                <div className="max-h-60 overflow-y-auto space-y-2 border rounded-md p-4">
                  {documents.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Нет загруженных документов. Загрузите документы в разделе E-Discovery.
                    </p>
                  ) : (
                    documents.map((doc) => (
                      <div
                        key={doc.id}
                        className="flex items-center justify-between p-2 rounded border hover:bg-muted cursor-pointer"
                        onClick={() => {
                          setSelectedDocuments((prev) =>
                            prev.includes(doc.id)
                              ? prev.filter((id) => id !== doc.id)
                              : [...prev, doc.id]
                          );
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4" />
                          <span className="text-sm">{doc.originalName}</span>
                        </div>
                        {selectedDocuments.includes(doc.id) && (
                          <Badge variant="secondary">Выбран</Badge>
                        )}
                      </div>
                    ))
                  )}
                </div>
                {selectedDocuments.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Выбрано: {selectedDocuments.length} документ{selectedDocuments.length > 1 ? "ов" : ""}
                  </p>
                )}
              </div>
            </div>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowCreateDialog(false)}
              >
                Отмена
              </Button>
              <Button onClick={handleCreateReview} disabled={loading || !newReviewTitle.trim() || selectedDocuments.length === 0}>
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Создать
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {selectedReview ? (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>{selectedReview.title}</CardTitle>
                  {selectedReview.description && (
                    <CardDescription>{selectedReview.description}</CardDescription>
                  )}
                </div>
                <div className="flex gap-2">
                  <Dialog open={showAddColumnDialog} onOpenChange={setShowAddColumnDialog}>
                    <DialogTrigger asChild>
                      <Button variant="outline" size="sm">
                        <PlusCircle className="mr-2 h-4 w-4" />
                        Добавить колонку
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Добавить колонку</DialogTitle>
                        <DialogDescription>
                          Создайте запрос для извлечения данных из документов
                        </DialogDescription>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor="column-title">Название колонки *</Label>
                          <Input
                            id="column-title"
                            value={newColumnTitle}
                            onChange={(e) => setNewColumnTitle(e.target.value)}
                            placeholder="Например: Сумма контракта"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="column-query">Запрос для извлечения *</Label>
                          <Textarea
                            id="column-query"
                            value={newColumnQuery}
                            onChange={(e) => setNewColumnQuery(e.target.value)}
                            placeholder="Например: Какая сумма указана в контракте?"
                            rows={3}
                          />
                        </div>
                      </div>
                      <DialogFooter>
                        <Button
                          variant="outline"
                          onClick={() => setShowAddColumnDialog(false)}
                        >
                          Отмена
                        </Button>
                        <Button onClick={handleAddColumn} disabled={loading || !newColumnTitle.trim() || !newColumnQuery.trim()}>
                          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                          Добавить
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleProcess}
                    disabled={processing || selectedReview.columns.length === 0}
                  >
                    {processing ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    Обработать
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleExport}>
                    <Download className="mr-2 h-4 w-4" />
                    Экспорт
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {processing && (
                <div className="mb-4 space-y-2">
                  <Progress value={processingProgress} />
                  <p className="text-sm text-muted-foreground">
                    Обработка документов... {processingProgress}%
                  </p>
                </div>
              )}

              {selectedReview.columns.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <p>Добавьте колонки для начала работы</p>
                </div>
              ) : (
                <div className="border rounded-md overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[200px]">Документ</TableHead>
                        {selectedReview.columns
                          .sort((a, b) => a.order - b.order)
                          .map((column) => (
                            <TableHead key={column.id}>{column.title}</TableHead>
                          ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {selectedReview.documentIds.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={selectedReview.columns.length + 1} className="text-center text-muted-foreground">
                            Нет документов
                          </TableCell>
                        </TableRow>
                      ) : (
                        selectedReview.documentIds.map((docId) => {
                          const doc = documents.find((d) => d.id === docId);
                          return (
                            <TableRow key={docId}>
                              <TableCell className="font-medium">
                                {doc?.originalName || docId}
                              </TableCell>
                              {selectedReview.columns
                                .sort((a, b) => a.order - b.order)
                                .map((column) => {
                                  const cell = getCellValue(docId, column.id);
                                  return (
                                    <TableCell
                                      key={column.id}
                                      className={cell?.citation ? "cursor-pointer hover:bg-muted/50" : ""}
                                      onClick={() => {
                                        if (cell?.citation) {
                                          setSelectedCell({
                                            documentId: docId,
                                            columnId: column.id,
                                            value: cell.value,
                                            citation: cell.citation,
                                          });
                                        }
                                      }}
                                    >
                                      {cell ? (
                                        <div className="space-y-1">
                                          <div>{cell.value}</div>
                                          {cell.confidence !== undefined && (
                                            <Badge
                                              variant={
                                                cell.confidence > 0.8
                                                  ? "default"
                                                  : cell.confidence > 0.5
                                                  ? "secondary"
                                                  : "outline"
                                              }
                                              className="text-xs"
                                            >
                                              {Math.round(cell.confidence * 100)}%
                                            </Badge>
                                          )}
                                          {cell.citation && (
                                            <p className="text-xs text-muted-foreground">
                                              Нажмите для просмотра источника
                                            </p>
                                          )}
                                        </div>
                                      ) : (
                                        <span className="text-muted-foreground">—</span>
                                      )}
                                    </TableCell>
                                  );
                                })}
                            </TableRow>
                          );
                        })
                      )}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Мои таблицы</CardTitle>
              <CardDescription>
                Выберите таблицу или создайте новую
              </CardDescription>
            </CardHeader>
            <CardContent>
              {reviews.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <p>У вас пока нет таблиц</p>
                  <p className="text-sm mt-2">Создайте новую таблицу для начала работы</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {(reviews as TabularReview[]).map((review) => (
                    <div
                      key={review.id}
                      className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                        selectedReview?.id === review.id
                          ? "bg-primary/10 border-primary"
                          : "hover:bg-muted"
                      }`}
                      onClick={() => loadReview(review.id)}
                    >
                      <p className="text-sm font-medium">{review.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {review.columns.length} колонок, {review.documentIds.length} документов
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Выберите таблицу</CardTitle>
              <CardDescription>
                Выберите таблицу из списка слева или создайте новую
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-center py-8 text-muted-foreground">
                <p>Выберите таблицу для просмотра</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Диалог просмотра цитаты */}
      <Dialog open={!!selectedCell} onOpenChange={() => setSelectedCell(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Источник данных</DialogTitle>
            <DialogDescription>
              Цитата из документа
            </DialogDescription>
          </DialogHeader>
          {selectedCell && (
            <div className="space-y-4">
              <div>
                <Label>Значение</Label>
                <p className="text-sm mt-1">{selectedCell.value}</p>
              </div>
              {selectedCell.citation && (
                <div>
                  <Label>Источник</Label>
                  <div className="mt-1 p-3 bg-muted rounded-md">
                    <p className="text-sm font-medium mb-2">
                      {selectedCell.citation.filename || "Документ"}
                    </p>
                    {selectedCell.citation.text && (
                      <p className="text-sm text-muted-foreground">
                        {selectedCell.citation.text}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
