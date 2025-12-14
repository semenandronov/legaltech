export type SummaryLength = "SHORT" | "MEDIUM" | "DETAILED";

export interface KeyElements {
  parties: {
    plaintiff?: string;
    defendant?: string;
  };
  dates: string[];
  amounts: string[];
  requirements: string[];
}

export interface SummaryResult {
  summary: string;
  keyElements: KeyElements;
}

export interface EmbeddingResult {
  embedding: number[];
}

export interface TimelineEvent {
  date: string;
  description: string;
  eventType?: string;
}

export interface TimelineResult {
  events: TimelineEvent[];
}

// Мок для суммирования документов
export const mockSummarize = async (
  text: string,
  length: SummaryLength
): Promise<SummaryResult> => {
  // Имитация задержки API
  await new Promise((resolve) => setTimeout(resolve, 1000));

  const wordCount = text.split(/\s+/).length;
  let summaryLength = 50;

  switch (length) {
    case "SHORT":
      summaryLength = Math.max(20, Math.floor(wordCount * 0.1));
      break;
    case "MEDIUM":
      summaryLength = Math.max(50, Math.floor(wordCount * 0.2));
      break;
    case "DETAILED":
      summaryLength = Math.max(100, Math.floor(wordCount * 0.3));
      break;
  }

  // Простое извлечение первых предложений как резюме
  const sentences = text.match(/[^.!?]+[.!?]+/g) || [];
  const summary = sentences.slice(0, Math.min(summaryLength / 10, sentences.length)).join(" ");

  // Извлечение ключевых элементов (упрощенная версия)
  const keyElements: KeyElements = {
    parties: {},
    dates: [],
    amounts: [],
    requirements: [],
  };

  // Поиск истца и ответчика
  const plaintiffMatch = text.match(/истец[^\n]*?([А-ЯЁ][А-Яа-яё\s]+(?:ООО|ИП|АО|ЗАО)[А-Яа-яё\s]*)/i);
  if (plaintiffMatch) {
    keyElements.parties.plaintiff = plaintiffMatch[1].trim();
  }

  const defendantMatch = text.match(/ответчик[^\n]*?([А-ЯЁ][А-Яа-яё\s]+(?:ООО|ИП|АО|ЗАО)[А-Яа-яё\s]*)/i);
  if (defendantMatch) {
    keyElements.parties.defendant = defendantMatch[1].trim();
  }

  // Поиск дат
  const datePattern = /\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}/g;
  const dates = text.match(datePattern) || [];
  keyElements.dates = [...new Set(dates)].slice(0, 10);

  // Поиск сумм
  const amountPattern = /\d{1,3}(?:\s?\d{3})*(?:\s?рублей?|руб\.?|₽)/gi;
  const amounts = text.match(amountPattern) || [];
  keyElements.amounts = [...new Set(amounts)].slice(0, 10);

  // Поиск требований
  const requirementKeywords = ["требует", "просит", "ходатайствует", "заявляет"];
  const requirementSentences = sentences.filter((s) =>
    requirementKeywords.some((keyword) => s.toLowerCase().includes(keyword))
  );
  keyElements.requirements = requirementSentences.slice(0, 5);

  return {
    summary: summary || "Не удалось создать резюме. Текст слишком короткий или некорректный.",
    keyElements,
  };
};

// Мок для генерации embeddings
export const mockGenerateEmbedding = async (text: string): Promise<EmbeddingResult> => {
  // Имитация задержки API
  await new Promise((resolve) => setTimeout(resolve, 500));

  // Генерируем случайный вектор размерности 1536 (как у OpenAI text-embedding-3)
  const embedding = Array.from({ length: 1536 }, () => Math.random() - 0.5);
  
  // Нормализуем вектор
  const magnitude = Math.sqrt(embedding.reduce((sum, val) => sum + val * val, 0));
  const normalized = embedding.map((val) => val / magnitude);

  return {
    embedding: normalized,
  };
};

// Мок для извлечения событий из текста
export const mockExtractTimelineEvents = async (text: string): Promise<TimelineResult> => {
  // Имитация задержки API
  await new Promise((resolve) => setTimeout(resolve, 1000));

  const events: TimelineEvent[] = [];

  // Поиск дат и связанных с ними событий
  const datePattern = /(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})/g;
  const sentences = text.match(/[^.!?]+[.!?]+/g) || [];

  sentences.forEach((sentence) => {
    const dateMatch = sentence.match(datePattern);
    if (dateMatch) {
      const date = dateMatch[0];
      // Очищаем предложение от лишних пробелов
      const description = sentence.trim().replace(/\s+/g, " ");
      
      // Определяем тип события
      let eventType: string | undefined;
      if (description.toLowerCase().includes("подписан") || description.toLowerCase().includes("заключен")) {
        eventType = "contract";
      } else if (description.toLowerCase().includes("переведен") || description.toLowerCase().includes("оплачен")) {
        eventType = "payment";
      } else if (description.toLowerCase().includes("подал") || description.toLowerCase().includes("подано")) {
        eventType = "lawsuit";
      } else if (description.toLowerCase().includes("выполнен") || description.toLowerCase().includes("завершен")) {
        eventType = "completion";
      }

      events.push({
        date,
        description,
        eventType,
      });
    }
  });

  // Упорядочиваем события по дате
  events.sort((a, b) => {
    const dateA = parseDate(a.date);
    const dateB = parseDate(b.date);
    return dateA.getTime() - dateB.getTime();
  });

  return {
    events: events.slice(0, 50), // Ограничиваем 50 событиями
  };
};

// Вспомогательная функция для парсинга дат
const parseDate = (dateStr: string): Date => {
  const parts = dateStr.split(/[.\-\/]/);
  if (parts.length === 3) {
    const day = parseInt(parts[0], 10);
    const month = parseInt(parts[1], 10) - 1;
    const year = parseInt(parts[2], 10) < 100 ? 2000 + parseInt(parts[2], 10) : parseInt(parts[2], 10);
    return new Date(year, month, day);
  }
  return new Date();
};

