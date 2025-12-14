export interface ParseResult {
  text: string;
  metadata?: Record<string, any>;
}

export const parseText = async (buffer: Buffer): Promise<ParseResult> => {
  try {
    const text = buffer.toString("utf-8");
    return {
      text,
      metadata: {
        encoding: "utf-8",
        size: buffer.length,
      },
    };
  } catch (error) {
    throw new Error(`Ошибка при парсинге текста: ${error instanceof Error ? error.message : "Неизвестная ошибка"}`);
  }
};

