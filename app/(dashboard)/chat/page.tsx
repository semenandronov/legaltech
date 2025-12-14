"use client";

import { useState, useEffect, useRef } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

// Отключаем статическую генерацию для этой страницы
export const dynamic = 'force-dynamic';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Loader2, Send, FileText, MessageSquare, Plus, Trash2, X } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { Badge } from "@/components/ui/badge";

interface Document {
  id: string;
  filename: string;
  originalName: string;
}

interface ChatSession {
  id: string;
  title: string;
  documentIds: string[];
  updatedAt: string;
  _count: { messages: number };
}

export default function ChatPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const { toast } = useToast();
  const [messages, setMessages] = useState<any[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [showNewSessionDialog, setShowNewSessionDialog] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Загрузка сессий и документов
  useEffect(() => {
    if (!session) {
      router.push("/login");
      return;
    }
    const loadData = async () => {
      try {
        const [sessionsRes, documentsRes] = await Promise.all([
          fetch("/api/chat/sessions"),
          fetch("/api/documents"),
        ]);

        if (sessionsRes.ok) {
          const sessionsData = await sessionsRes.json();
          setSessions(sessionsData.sessions || []);
          if (sessionsData.sessions?.length > 0) {
            setSessionId(sessionsData.sessions[0].id);
            loadSessionMessages(sessionsData.sessions[0].id);
          }
        }

        if (documentsRes.ok) {
          const documentsData = await documentsRes.json();
          setDocuments(documentsData.documents || []);
        }
      } catch (error) {
        toast({
          variant: "destructive",
          title: "Ошибка",
          description: "Не удалось загрузить данные",
        });
      } finally {
        setLoadingSessions(false);
      }
    };

    if (session) {
      loadData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const loadSessionMessages = async (id: string) => {
    try {
      const response = await fetch(`/api/chat/sessions/${id}`);
      if (response.ok) {
        const data = await response.json();
        setMessages(data.session.messages || []);
        setSelectedDocuments(data.session.documentIds || []);
      }
    } catch (error) {
      console.error("Error loading session:", error);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  if (!session) {
    return null;
  }

  const handleCreateSession = async () => {
    if (selectedDocuments.length === 0) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Выберите хотя бы один документ",
      });
      return;
    }

    try {
      const response = await fetch("/api/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: `Чат с ${selectedDocuments.length} документ${selectedDocuments.length > 1 ? "ами" : "ом"}`,
          documentIds: selectedDocuments,
        }),
      });

      if (!response.ok) throw new Error("Ошибка создания сессии");

      const data = await response.json();
      setSessionId(data.session.id);
      setMessages([]);
      setSessions((prev) => [data.session, ...prev]);
      setShowNewSessionDialog(false);
      toast({
        variant: "success",
        title: "Успешно",
        description: "Новая сессия создана",
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Не удалось создать сессию",
      });
    }
  };

  const handleDeleteSession = async (id: string) => {
    try {
      const response = await fetch(`/api/chat/sessions/${id}`, {
        method: "DELETE",
      });

      if (!response.ok) throw new Error("Ошибка удаления");

      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (sessionId === id) {
        setSessionId(null);
        setMessages([]);
      }
      toast({
        variant: "success",
        title: "Успешно",
        description: "Сессия удалена",
      });
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Не удалось удалить сессию",
      });
    }
  };

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    if (!sessionId) {
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: "Создайте или выберите сессию",
      });
      return;
    }

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setLoading(true);

    try {
      const response = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId,
          message: userMessage,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Ошибка при отправке сообщения");
      }

      const data = await response.json();
      setSessionId(data.sessionId);
      setMessages((prev) => [...prev, data.message]);
      
      // Обновляем список сессий
      setSessions((prev) =>
        prev.map((s) =>
          s.id === data.sessionId
            ? { ...s, updatedAt: new Date().toISOString() }
            : s
        )
      );
    } catch (error) {
      console.error("Error sending message:", error);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Ошибка: ${error instanceof Error ? error.message : "Произошла ошибка. Попробуйте еще раз."}`,
        },
      ]);
      toast({
        variant: "destructive",
        title: "Ошибка",
        description: error instanceof Error ? error.message : "Не удалось отправить сообщение",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Чат с ИИ</h1>
          <p className="text-muted-foreground mt-2">
            Задавайте вопросы по документам и получайте ответы с цитированием источников
          </p>
        </div>
        <Dialog open={showNewSessionDialog} onOpenChange={setShowNewSessionDialog}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Новая сессия
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Создать новую сессию</DialogTitle>
              <DialogDescription>
                Выберите документы для контекста чата
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Документы</Label>
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
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowNewSessionDialog(false)}
                >
                  Отмена
                </Button>
                <Button onClick={handleCreateSession} disabled={selectedDocuments.length === 0}>
                  Создать
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid gap-6 lg:grid-cols-4">
        {/* Боковая панель с сессиями */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-lg">Сессии</CardTitle>
          </CardHeader>
          <CardContent>
            {loadingSessions ? (
              <div className="flex justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin" />
              </div>
            ) : sessions.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                Нет сессий. Создайте новую.
              </p>
            ) : (
              <div className="space-y-2">
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      sessionId === session.id
                        ? "bg-primary/10 border-primary"
                        : "hover:bg-muted"
                    }`}
                    onClick={() => {
                      setSessionId(session.id);
                      loadSessionMessages(session.id);
                    }}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{session.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {session._count.messages} сообщений
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteSession(session.id);
                        }}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Основной чат */}
        <Card className="lg:col-span-3 h-[600px] flex flex-col">
          <CardHeader>
            <CardTitle>Диалог</CardTitle>
            <CardDescription>
              {sessionId
                ? "Ассистент анализирует ваши документы и отвечает на вопросы"
                : "Создайте новую сессию для начала диалога"}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto space-y-4 mb-4">
              {!sessionId ? (
                <div className="text-center text-muted-foreground py-8">
                  <MessageSquare className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>Создайте новую сессию для начала диалога</p>
                </div>
              ) : messages.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">
                  <p>Начните диалог, задав вопрос</p>
                </div>
              ) : (
                messages.map((msg, index) => (
                  <div
                    key={index}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg p-4 ${
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted"
                      }`}
                    >
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                      {msg.citations && msg.citations.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-border/50">
                          <p className="text-xs font-semibold mb-1">Источники:</p>
                          {msg.citations.map((citation: any, idx: number) => (
                            <div
                              key={idx}
                              className="text-xs flex items-center gap-1 hover:underline cursor-pointer"
                              onClick={() => {
                                // Можно добавить переход к документу
                              }}
                            >
                              <FileText className="h-3 w-3" />
                              <span>{citation.filename}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-muted rounded-lg p-4">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
            <div className="flex gap-2">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={sessionId ? "Задайте вопрос..." : "Создайте сессию для начала"}
                disabled={loading || !sessionId}
              />
              <Button
                onClick={handleSend}
                disabled={loading || !input.trim() || !sessionId}
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
