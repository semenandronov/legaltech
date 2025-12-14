import {
  mockSummarize,
  mockGenerateEmbedding,
  mockExtractTimelineEvents,
  type SummaryLength,
  type SummaryResult,
  type EmbeddingResult,
  type TimelineResult,
} from "./mocks";
import {
  summarizeWithOpenAI,
  generateEmbeddingWithOpenAI,
  extractTimelineEventsWithOpenAI,
} from "./openai";

// Используем моки, если нет API ключа, иначе реальный OpenAI
const useMocks = !process.env.OPENAI_API_KEY;

export const summarize = async (
  text: string,
  length: SummaryLength
): Promise<SummaryResult> => {
  if (useMocks) {
    return mockSummarize(text, length);
  }
  return summarizeWithOpenAI(text, length);
};

export const generateEmbedding = async (text: string): Promise<EmbeddingResult> => {
  if (useMocks) {
    return mockGenerateEmbedding(text);
  }
  return generateEmbeddingWithOpenAI(text);
};

export const extractTimelineEvents = async (text: string): Promise<TimelineResult> => {
  if (useMocks) {
    return mockExtractTimelineEvents(text);
  }
  return extractTimelineEventsWithOpenAI(text);
};

export type { SummaryLength, SummaryResult, EmbeddingResult, TimelineResult };

