import OpenAI from "openai";
import type { SummaryLength, SummaryResult, EmbeddingResult, TimelineResult } from "./mocks";

// Ленивая инициализация OpenAI клиента
const getOpenAI = () => {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error("OPENAI_API_KEY is not configured");
  }
  return new OpenAI({ apiKey });
};

const MODEL = process.env.OPENAI_MODEL || "gpt-4o";

// Реальная реализация суммирования через OpenAI
export const summarizeWithOpenAI = async (
  text: string,
  length: SummaryLength
): Promise<SummaryResult> => {
  const lengthInstructions = {
    SHORT: "Создайте очень краткое резюме (2-3 предложения)",
    MEDIUM: "Создайте среднее резюме (5-7 предложений)",
    DETAILED: "Создайте подробное резюме (10-15 предложений)",
  };

  const prompt = `Ты - эксперт по анализу юридических документов. Проанализируй следующий судебный документ и создай резюме.

${lengthInstructions[length]}

Документ:
${text}

Верни ответ в формате JSON:
{
  "summary": "резюме документа",
  "keyElements": {
    "parties": {
      "plaintiff": "название истца или null",
      "defendant": "название ответчика или null"
    },
    "dates": ["список всех важных дат"],
    "amounts": ["список всех сумм с указанием валюты"],
    "requirements": ["список требований истца/ответчика"]
  }
}`;

  const openai = getOpenAI();
  const response = await openai.chat.completions.create({
    model: MODEL,
    messages: [
      {
        role: "system",
        content: "Ты - эксперт по анализу юридических документов. Всегда отвечай валидным JSON.",
      },
      {
        role: "user",
        content: prompt,
      },
    ],
    response_format: { type: "json_object" },
    temperature: 0.3,
  });

  const result = JSON.parse(response.choices[0].message.content || "{}");
  return result as SummaryResult;
};

// Реальная реализация генерации embeddings
export const generateEmbeddingWithOpenAI = async (text: string): Promise<EmbeddingResult> => {
  const openai = getOpenAI();
  const response = await openai.embeddings.create({
    model: "text-embedding-3-small",
    input: text,
  });

  return {
    embedding: response.data[0].embedding,
  };
};

// Реальная реализация извлечения событий
export const extractTimelineEventsWithOpenAI = async (text: string): Promise<TimelineResult> => {
  const prompt = `Ты - эксперт по анализу юридических документов. Извлеки из следующего текста все события с датами и создай хронологию.

Текст:
${text}

Верни ответ в формате JSON:
{
  "events": [
    {
      "date": "дата в формате ДД.ММ.ГГГГ",
      "description": "описание события",
      "eventType": "тип события (contract, payment, lawsuit, completion, violation, или другой)"
    }
  ]
}

События должны быть упорядочены по дате (от старых к новым).`;

  const openai = getOpenAI();
  const response = await openai.chat.completions.create({
    model: MODEL,
    messages: [
      {
        role: "system",
        content: "Ты - эксперт по анализу юридических документов. Всегда отвечай валидным JSON.",
      },
      {
        role: "user",
        content: prompt,
      },
    ],
    response_format: { type: "json_object" },
    temperature: 0.2,
  });

  const result = JSON.parse(response.choices[0].message.content || "{}");
  return result as TimelineResult;
};

