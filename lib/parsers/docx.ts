import mammoth from "mammoth";

export interface ParseResult {
  text: string;
  metadata?: {
    messages?: string[];
  };
}

export const parseDOCX = async (buffer: Buffer): Promise<ParseResult> => {
  try {
    const result = await mammoth.extractRawText({ buffer });
    return {
      text: result.value,
      metadata: {
        messages: result.messages.map((msg) => 
          typeof msg === 'string' ? msg : msg.message || String(msg)
        ),
      },
    };
  } catch (error) {
    throw new Error(`Ошибка при парсинге DOCX: ${error instanceof Error ? error.message : "Неизвестная ошибка"}`);
  }
};

