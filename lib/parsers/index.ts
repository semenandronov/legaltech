import { parsePDF } from "./pdf";
import { parseDOCX } from "./docx";
import { parseText } from "./text";

export type ParseResult = {
  text: string;
  metadata?: Record<string, any>;
};

export const parseFile = async (
  buffer: Buffer,
  mimeType: string,
  filename: string
): Promise<ParseResult> => {
  const extension = filename.split(".").pop()?.toLowerCase();

  if (mimeType === "application/pdf" || extension === "pdf") {
    return parsePDF(buffer);
  }

  if (
    mimeType ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    extension === "docx"
  ) {
    return parseDOCX(buffer);
  }

  if (
    mimeType === "text/plain" ||
    mimeType === "text/html" ||
    extension === "txt" ||
    extension === "html"
  ) {
    return parseText(buffer);
  }

  throw new Error(
    `Неподдерживаемый тип файла: ${mimeType}. Поддерживаются: PDF, DOCX, TXT`
  );
};

export { parsePDF, parseDOCX, parseText };

