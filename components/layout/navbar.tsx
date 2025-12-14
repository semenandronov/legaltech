"use client";

import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { Button } from "@/components/ui/button";
import { FileText, Search, Calendar, Home, MessageSquare, Table } from "lucide-react";

export const Navbar = () => {
  const { data: session } = useSession();

  return (
    <nav className="border-b bg-background">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          <div className="flex items-center space-x-8">
            <Link href="/dashboard" className="flex items-center space-x-2">
              <FileText className="h-6 w-6" />
              <span className="text-xl font-bold">Legal AI Assistant</span>
            </Link>
            {session && (
              <div className="flex items-center space-x-4">
                <Link href="/dashboard">
                  <Button variant="ghost" size="sm">
                    <Home className="mr-2 h-4 w-4" />
                    Главная
                  </Button>
                </Link>
                <Link href="/dashboard/summarize" prefetch={false}>
                  <Button variant="ghost" size="sm">
                    <FileText className="mr-2 h-4 w-4" />
                    Суммирование
                  </Button>
                </Link>
                <Link href="/dashboard/ediscovery" prefetch={false}>
                  <Button variant="ghost" size="sm">
                    <Search className="mr-2 h-4 w-4" />
                    E-Discovery
                  </Button>
                </Link>
                <Link href="/dashboard/timeline" prefetch={false}>
                  <Button variant="ghost" size="sm">
                    <Calendar className="mr-2 h-4 w-4" />
                    Хронология
                  </Button>
                </Link>
                <Link href="/dashboard/chat" prefetch={false}>
                  <Button variant="ghost" size="sm">
                    <MessageSquare className="mr-2 h-4 w-4" />
                    Чат с ИИ
                  </Button>
                </Link>
                <Link href="/dashboard/tabular" prefetch={false}>
                  <Button variant="ghost" size="sm">
                    <Table className="mr-2 h-4 w-4" />
                    Табличный поиск
                  </Button>
                </Link>
              </div>
            )}
          </div>
          <div className="flex items-center space-x-4">
            {session ? (
              <>
                <span className="text-sm text-muted-foreground">
                  {session.user?.email}
                </span>
                <Button variant="outline" size="sm" onClick={() => signOut()}>
                  Выйти
                </Button>
              </>
            ) : (
              <>
                <Link href="/login">
                  <Button variant="ghost" size="sm">
                    Войти
                  </Button>
                </Link>
                <Link href="/register">
                  <Button size="sm">Регистрация</Button>
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
};

