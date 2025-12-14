import { z } from "zod";

// Схемы валидации для различных типов запросов

export const summarizeRequestSchema = z.object({
  text: z.string().min(50, "Текст должен содержать минимум 50 символов").optional(),
  length: z.enum(["SHORT", "MEDIUM", "DETAILED"]).default("MEDIUM"),
});

export const searchRequestSchema = z.object({
  query: z.string().min(1, "Поисковый запрос не может быть пустым"),
  searchType: z.enum(["KEYWORD", "SEMANTIC", "HYBRID"]).default("KEYWORD"),
  documentIds: z.array(z.string()).optional(),
  limit: z.number().int().min(1).max(100).default(20),
});

export const timelineRequestSchema = z.object({
  text: z.string().min(50, "Текст должен содержать минимум 50 символов"),
  title: z.string().optional(),
});

export const registerRequestSchema = z.object({
  email: z.string().email("Некорректный email"),
  password: z.string().min(6, "Пароль должен содержать минимум 6 символов"),
  name: z.string().optional(),
});

