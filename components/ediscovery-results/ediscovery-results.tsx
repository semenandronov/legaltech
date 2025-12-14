"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText, Search, TrendingUp } from "lucide-react";

interface SearchResult {
  documentId: string;
  documentName: string;
  relevance: number;
  context: string;
  highlights: number;
  matchType?: string;
  semanticRelevance?: number;
}

interface SearchResponse {
  query: string;
  searchType: string;
  totalDocuments: number;
  totalResults: number;
  results: SearchResult[];
  statistics: {
    documentsFound: number;
    totalMatches: number;
    averageMatchesPerDocument: number;
  };
}

interface EDiscoveryResultsProps {
  data: SearchResponse | null;
  loading?: boolean;
}

export const EDiscoveryResults = ({ data, loading }: EDiscoveryResultsProps) => {
  if (loading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-center h-64">
            <p className="text-muted-foreground">Поиск...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            <p>Результаты поиска появятся здесь</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const highlightQuery = (text: string, query: string) => {
    const words = query.split(/\s+/).filter((w) => w.length > 2);
    let highlighted = text;
    words.forEach((word) => {
      const regex = new RegExp(`(${word})`, "gi");
      highlighted = highlighted.replace(
        regex,
        '<mark class="bg-yellow-200 dark:bg-yellow-900">$1</mark>'
      );
    });
    return highlighted;
  };

  return (
    <div className="space-y-6">
      {/* Статистика */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            Статистика поиска
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">Документов найдено</p>
              <p className="text-2xl font-bold">{data.statistics.documentsFound}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Всего совпадений</p>
              <p className="text-2xl font-bold">{data.statistics.totalMatches}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Среднее на документ</p>
              <p className="text-2xl font-bold">
                {data.statistics.averageMatchesPerDocument.toFixed(1)}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Всего документов</p>
              <p className="text-2xl font-bold">{data.totalDocuments}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Результаты */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold">Результаты поиска</h2>
          <Badge variant="outline">
            {data.totalResults} {data.totalResults === 1 ? "результат" : "результатов"}
          </Badge>
        </div>

        {data.results.length === 0 ? (
          <Card>
            <CardContent className="pt-6">
              <div className="text-center py-8 text-muted-foreground">
                <Search className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>Ничего не найдено</p>
                <p className="text-sm mt-2">
                  Попробуйте изменить поисковый запрос или тип поиска
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          data.results.map((result, index) => (
            <Card key={result.documentId}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <FileText className="h-5 w-5 text-primary" />
                    <div>
                      <CardTitle className="text-lg">{result.documentName}</CardTitle>
                      <CardDescription>
                        Релевантность: {(result.relevance * 100).toFixed(1)}%
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {result.matchType && (
                      <Badge variant="secondary">{result.matchType}</Badge>
                    )}
                    <Badge variant="outline">
                      {result.highlights} {result.highlights === 1 ? "совпадение" : "совпадений"}
                    </Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div
                  className="prose prose-sm max-w-none dark:prose-invert"
                  dangerouslySetInnerHTML={{
                    __html: highlightQuery(result.context, data.query),
                  }}
                />
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
};

