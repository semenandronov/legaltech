import pdfParse from "pdf-parse";

export interface ParseResult {
  text: string;
  metadata?: {
    pages?: number;
    info?: any;
  };
}

export const parsePDF = async (buffer: Buffer): Promise<ParseResult> => {
  try {
    const data = await pdfParse(buffer);
    return {
      text: data.text,
      metadata: {
        pages: data.numpages,
        info: data.info,
      },
    };
  } catch (error) {
    throw new Error(`Ошибка при парсинге PDF: ${error instanceof Error ? error.message : "Неизвестная ошибка"}`);
  }
};

