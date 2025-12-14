"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Calendar, DollarSign, Users, FileText } from "lucide-react";
import type { SummaryResult } from "@/lib/ai";

interface SummaryResultProps {
  result: SummaryResult;
}

export const SummaryResultComponent = ({ result }: SummaryResultProps) => {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Резюме документа</CardTitle>
          <CardDescription>Краткое изложение ключевой информации</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-base leading-relaxed whitespace-pre-wrap">
            {result.summary}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ключевые элементы</CardTitle>
          <CardDescription>Извлеченная структурированная информация</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="parties" className="w-full">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="parties">
                <Users className="h-4 w-4 mr-2" />
                Стороны
              </TabsTrigger>
              <TabsTrigger value="dates">
                <Calendar className="h-4 w-4 mr-2" />
                Даты
              </TabsTrigger>
              <TabsTrigger value="amounts">
                <DollarSign className="h-4 w-4 mr-2" />
                Суммы
              </TabsTrigger>
              <TabsTrigger value="requirements">
                <FileText className="h-4 w-4 mr-2" />
                Требования
              </TabsTrigger>
            </TabsList>

            <TabsContent value="parties" className="mt-4">
              <div className="space-y-4">
                {result.keyElements.parties.plaintiff && (
                  <div>
                    <p className="text-sm font-medium text-muted-foreground mb-1">
                      Истец:
                    </p>
                    <p className="text-base">{result.keyElements.parties.plaintiff}</p>
                  </div>
                )}
                {result.keyElements.parties.defendant && (
                  <div>
                    <p className="text-sm font-medium text-muted-foreground mb-1">
                      Ответчик:
                    </p>
                    <p className="text-base">{result.keyElements.parties.defendant}</p>
                  </div>
                )}
                {!result.keyElements.parties.plaintiff &&
                  !result.keyElements.parties.defendant && (
                    <p className="text-muted-foreground">
                      Стороны не найдены в документе
                    </p>
                  )}
              </div>
            </TabsContent>

            <TabsContent value="dates" className="mt-4">
              {result.keyElements.dates.length > 0 ? (
                <ul className="space-y-2">
                  {result.keyElements.dates.map((date, index) => (
                    <li key={index} className="flex items-center gap-2">
                      <Calendar className="h-4 w-4 text-muted-foreground" />
                      <span>{date}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">Даты не найдены в документе</p>
              )}
            </TabsContent>

            <TabsContent value="amounts" className="mt-4">
              {result.keyElements.amounts.length > 0 ? (
                <ul className="space-y-2">
                  {result.keyElements.amounts.map((amount, index) => (
                    <li key={index} className="flex items-center gap-2">
                      <DollarSign className="h-4 w-4 text-muted-foreground" />
                      <span>{amount}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">Суммы не найдены в документе</p>
              )}
            </TabsContent>

            <TabsContent value="requirements" className="mt-4">
              {result.keyElements.requirements.length > 0 ? (
                <ul className="space-y-3">
                  {result.keyElements.requirements.map((requirement, index) => (
                    <li key={index} className="flex items-start gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground mt-1 flex-shrink-0" />
                      <span className="text-base">{requirement}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">
                  Требования не найдены в документе
                </p>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
};

