import OpenAI from "openai";
import { prisma } from "@/lib/db/prisma";
import { generateEmbedding } from "./index";

// Ленивая инициализация OpenAI клиента
const getOpenAI = () => {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error("OPENAI_API_KEY is not configured");
  }
  return new OpenAI({ apiKey });
};

const MODEL = process.env.OPENAI_MODEL || "gpt-4o";

interface ChatContext {
  documents: Array<{
    id: string;
    filename: string;
    content: string;
  }>;
  history: Array<{
    role: "user" | "assistant";
    content: string;
  }>;
}

// Поиск релевантных документов для контекста
const findRelevantDocuments = async (
  query: string,
  documentIds: string[],
  userId: string,
  limit: number = 5
) => {
  if (documentIds.length === 0) {
    return [];
  }

  // Генерируем embedding для запроса
  const queryEmbedding = await generateEmbedding(query);
  const queryVector = queryEmbedding.embedding;

  // Получаем документы пользователя
  const documents = await prisma.document.findMany({
    where: {
      id: { in: documentIds },
      userId,
    },
    select: {
      id: true,
      filename: true,
      content: true,
    },
  });

  // Вычисляем релевантность (упрощенная версия - в реальности через pgvector)
  const documentsWithRelevance = documents.map((doc) => {
    // Для упрощения используем текстовый поиск
    const queryLower = query.toLowerCase();
    const contentLower = doc.content.toLowerCase();
    const matches = (contentLower.match(new RegExp(queryLower, "gi")) || []).length;
    const relevance = Math.min(1.0, matches / 10);

    return {
      ...doc,
      relevance,
    };
  });

  // Сортируем по релевантности и берем топ
  return documentsWithRelevance
    .sort((a, b) => b.relevance - a.relevance)
    .slice(0, limit)
    .map(({ relevance, ...doc }) => doc);
};

// Извлечение цитат из документа
const extractCitations = (
  answer: string,
  documents: Array<{ id: string; filename: string; content: string }>
): Array<{ documentId: string; filename: string; text: string; position: number }> => {
  const citations: Array<{ documentId: string; filename: string; text: string; position: number }> = [];

  // Ищем упоминания документов в ответе
  documents.forEach((doc) => {
    const docName = doc.filename.toLowerCase();
    const answerLower = answer.toLowerCase();

    if (answerLower.includes(docName)) {
      // Находим релевантный фрагмент из документа
      const sentences = doc.content.match(/[^.!?]+[.!?]+/g) || [];
      const relevantSentences = sentences
        .filter((s) => {
          const sLower = s.toLowerCase();
          return answerLower.split(/\s+/).some((word) => word.length > 3 && sLower.includes(word));
        })
        .slice(0, 2);

      if (relevantSentences.length > 0) {
        citations.push({
          documentId: doc.id,
          filename: doc.filename,
          text: relevantSentences.join(" "),
          position: answerLower.indexOf(docName),
        });
      }
    }
  });

  return citations;
};

// Генерация ответа с контекстом
export const generateChatResponse = async (
  message: string,
  context: ChatContext,
  userId: string
): Promise<{
  response: string;
  citations: Array<{ documentId: string; filename: string; text: string; position: number }>;
}> => {
  // Находим релевантные документы
  const relevantDocs = await findRelevantDocuments(
    message,
    context.documents.map((d) => d.id),
    userId
  );

  // Формируем контекст для промпта
  const documentsContext = relevantDocs
    .map((doc, index) => `[Документ ${index + 1}: ${doc.filename}]\n${doc.content.substring(0, 2000)}...`)
    .join("\n\n");

  const systemPrompt = `Ты - эксперт-ассистент по анализу юридических документов. 
Твоя задача - отвечать на вопросы пользователя на основе предоставленных документов.

Важные правила:
1. Всегда указывай источники информации (название документа)
2. Используй цитирование конкретных фрагментов из документов
3. Если информации нет в документах, честно скажи об этом
4. Отвечай на русском языке, если вопрос на русском
5. Будь точным и конкретным

Контекст документов:
${documentsContext || "Документы не предоставлены"}`;

  // Формируем историю сообщений
  const messages: any[] = [
    { role: "system", content: systemPrompt },
    ...context.history.slice(-10), // Последние 10 сообщений
    { role: "user", content: message },
  ];

  try {
    const openai = getOpenAI();
    const completion = await openai.chat.completions.create({
      model: MODEL,
      messages,
      temperature: 0.7,
    });

    const response = completion.choices[0].message.content || "Извините, не удалось сгенерировать ответ.";

    // Извлекаем цитаты
    const citations = extractCitations(response, relevantDocs);

    return {
      response,
      citations,
    };
  } catch (error) {
    console.error("Error generating chat response:", error);
    throw new Error("Failed to generate chat response");
  }
};

// Мок для разработки без OpenAI
export const mockGenerateChatResponse = async (
  message: string,
  context: ChatContext
): Promise<{
  response: string;
  citations: Array<{ documentId: string; filename: string; text: string; position: number }>;
}> => {
  await new Promise((resolve) => setTimeout(resolve, 1000));

  const response = `Это мок-ответ на ваш вопрос: "${message}". 
  
В реальной версии здесь будет ответ, сгенерированный ИИ на основе загруженных документов. 
Ответ будет содержать конкретные цитаты из документов с указанием источников.`;

  const citations = context.documents.slice(0, 2).map((doc, index) => ({
    documentId: doc.id,
    filename: doc.filename,
    text: doc.content.substring(0, 200) + "...",
    position: index * 100,
  }));

  return { response, citations };
};

