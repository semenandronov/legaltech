"use client";

import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { FileText, Search, Calendar, Home, MessageSquare, Table } from "lucide-react";

export const Navbar = () => {
  const { data: session } = useSession();
  const router = useRouter();

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
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => router.push("/dashboard/summarize")}
                >
                  <FileText className="mr-2 h-4 w-4" />
                  Суммирование
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => router.push("/dashboard/ediscovery")}
                >
                  <Search className="mr-2 h-4 w-4" />
                  E-Discovery
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => router.push("/dashboard/timeline")}
                >
                  <Calendar className="mr-2 h-4 w-4" />
                  Хронология
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => router.push("/dashboard/chat")}
                >
                  <MessageSquare className="mr-2 h-4 w-4" />
                  Чат с ИИ
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => router.push("/dashboard/tabular")}
                >
                  <Table className="mr-2 h-4 w-4" />
                  Табличный поиск
                </Button>
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

