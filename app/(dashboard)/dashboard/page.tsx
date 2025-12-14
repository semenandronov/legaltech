"use client";

import { useSession } from "next-auth/react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FileText, Search, Calendar, MessageSquare, Table } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function DashboardPage() {
  const { data: session } = useSession();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Добро пожаловать, {session?.user?.name || session?.user?.email}!</h1>
        <p className="text-muted-foreground mt-2">
          Выберите модуль для работы с судебными документами
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <FileText className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>Суммирование документов</CardTitle>
            <CardDescription>
              Создайте краткое резюме юридических документов и извлеките ключевые элементы
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/dashboard/summarize" prefetch={false}>
              <Button className="w-full">Начать</Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <Search className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>E-Discovery</CardTitle>
            <CardDescription>
              Быстрый поиск по множественным документам с использованием AI
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/dashboard/ediscovery" prefetch={false}>
              <Button className="w-full">Начать</Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <Calendar className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>Хронология событий</CardTitle>
            <CardDescription>
              Создайте упорядоченную временную шкалу событий из документов
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/dashboard/timeline" prefetch={false}>
              <Button className="w-full">Начать</Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <MessageSquare className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>Чат с ИИ</CardTitle>
            <CardDescription>
              Задавайте вопросы по документам и получайте ответы с цитированием источников
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/dashboard/chat" prefetch={false}>
              <Button className="w-full">Начать</Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <Table className="h-8 w-8 mb-2 text-primary" />
            <CardTitle>Табличный поиск</CardTitle>
            <CardDescription>
              Автоматическое извлечение данных из документов в таблицу
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/dashboard/tabular" prefetch={false}>
              <Button className="w-full">Начать</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

