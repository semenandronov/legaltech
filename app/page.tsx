"use client";

import { SessionProvider, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { FileText, Search, Calendar } from "lucide-react";

function HomeContent() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.push("/dashboard");
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center">
        <p>Загрузка...</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <div className="z-10 max-w-5xl w-full items-center justify-between">
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold mb-4">
            Legal AI Assistant
          </h1>
          <p className="text-xl text-muted-foreground mb-8">
            Веб-приложение для анализа судебных документов с использованием AI
          </p>
          <div className="flex gap-4 justify-center">
            <Link href="/login">
              <Button size="lg">Войти</Button>
            </Link>
            <Link href="/register">
              <Button size="lg" variant="outline">Регистрация</Button>
            </Link>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-6 mt-12">
          <div className="p-6 border rounded-lg">
            <FileText className="h-8 w-8 mb-4 text-primary" />
            <h3 className="text-lg font-semibold mb-2">Суммирование документов</h3>
            <p className="text-sm text-muted-foreground">
              Создавайте краткие резюме юридических документов и извлекайте ключевые элементы
            </p>
          </div>
          <div className="p-6 border rounded-lg">
            <Search className="h-8 w-8 mb-4 text-primary" />
            <h3 className="text-lg font-semibold mb-2">E-Discovery</h3>
            <p className="text-sm text-muted-foreground">
              Быстрый поиск по множественным документам с использованием AI
            </p>
          </div>
          <div className="p-6 border rounded-lg">
            <Calendar className="h-8 w-8 mb-4 text-primary" />
            <h3 className="text-lg font-semibold mb-2">Хронология событий</h3>
            <p className="text-sm text-muted-foreground">
              Создавайте упорядоченные временные шкалы событий из документов
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function Home() {
  return (
    <SessionProvider>
      <HomeContent />
    </SessionProvider>
  );
}

