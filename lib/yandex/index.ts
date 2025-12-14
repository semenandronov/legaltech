import axios from "axios";

// Yandex API конфигурация
const YANDEX_VISION_API_URL = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze";
const YANDEX_SPEECHKIT_API_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize";
const YANDEX_DOCUMENT_PARSER_API_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText";

interface YandexConfig {
  apiKey?: string;
  folderId?: string;
  iamToken?: string;
}

let config: YandexConfig = {
  apiKey: process.env.YANDEX_API_KEY,
  folderId: process.env.YANDEX_FOLDER_ID,
  iamToken: process.env.YANDEX_IAM_TOKEN,
};

export const setYandexConfig = (newConfig: YandexConfig) => {
  config = { ...config, ...newConfig };
};

// Получение IAM токена (если используется API ключ)
const getIamToken = async (): Promise<string | null> => {
  if (config.iamToken) {
    return config.iamToken;
  }

  if (!config.apiKey) {
    throw new Error("Yandex API key or IAM token required");
  }

  try {
    const response = await axios.post(
      "https://iam.api.cloud.yandex.net/iam/v1/tokens",
      {
        yandexPassportOauthToken: config.apiKey,
      }
    );
    return response.data.iamToken;
  } catch (error) {
    console.error("Error getting IAM token:", error);
    return null;
  }
};

// Извлечение текста из изображения/PDF через Yandex Vision
export const extractTextFromImage = async (
  imageBuffer: Buffer,
  mimeType: string
): Promise<string> => {
  const iamToken = await getIamToken();
  if (!iamToken) {
    throw new Error("Failed to get IAM token");
  }

  const base64Image = imageBuffer.toString("base64");

  try {
    const response = await axios.post(
      YANDEX_VISION_API_URL,
      {
        folderId: config.folderId,
        analyzeSpecs: [
          {
            content: base64Image,
            features: [
              {
                type: "TEXT_DETECTION",
                textDetectionConfig: {
                  languageCodes: ["ru", "en"],
                },
              },
            ],
            mimeType,
          },
        ],
      },
      {
        headers: {
          Authorization: `Bearer ${iamToken}`,
          "Content-Type": "application/json",
        },
      }
    );

    const textBlocks = response.data.results?.[0]?.results?.[0]?.textDetection?.blocks || [];
    const text = textBlocks
      .map((block: any) =>
        block.lines
          .map((line: any) => line.words.map((word: any) => word.text).join(" "))
          .join("\n")
      )
      .join("\n\n");

    return text || "";
  } catch (error) {
    console.error("Error extracting text from image:", error);
    throw new Error("Failed to extract text from image using Yandex Vision");
  }
};

// Извлечение текста из аудио/видео через Yandex SpeechKit
export const extractTextFromAudio = async (
  audioBuffer: Buffer,
  mimeType: string = "audio/ogg"
): Promise<string> => {
  const iamToken = await getIamToken();
  if (!iamToken) {
    throw new Error("Failed to get IAM token");
  }

  try {
    const response = await axios.post(
      `${YANDEX_SPEECHKIT_API_URL}?lang=ru-RU&format=${mimeType}&folderId=${config.folderId}`,
      audioBuffer,
      {
        headers: {
          Authorization: `Bearer ${iamToken}`,
          "Content-Type": mimeType,
        },
      }
    );

    return response.data.result || "";
  } catch (error) {
    console.error("Error extracting text from audio:", error);
    throw new Error("Failed to extract text from audio using Yandex SpeechKit");
  }
};

// Извлечение текста из документа через Yandex Document Parser
export const extractTextFromDocument = async (
  documentBuffer: Buffer,
  mimeType: string
): Promise<string> => {
  const iamToken = await getIamToken();
  if (!iamToken) {
    throw new Error("Failed to get IAM token");
  }

  const base64Document = documentBuffer.toString("base64");

  try {
    const response = await axios.post(
      YANDEX_DOCUMENT_PARSER_API_URL,
      {
        folderId: config.folderId,
        mimeType,
        languageCodes: ["ru", "en"],
        content: base64Document,
      },
      {
        headers: {
          Authorization: `Bearer ${iamToken}`,
          "Content-Type": "application/json",
        },
      }
    );

    const textBlocks = response.data.result?.textAnnotation?.blocks || [];
    const text = textBlocks
      .map((block: any) =>
        block.lines
          .map((line: any) => line.words.map((word: any) => word.text).join(" "))
          .join("\n")
      )
      .join("\n\n");

    return text || "";
  } catch (error) {
    console.error("Error extracting text from document:", error);
    throw new Error("Failed to extract text from document using Yandex Document Parser");
  }
};

// Универсальная функция для извлечения текста в зависимости от типа файла
export const extractTextWithYandex = async (
  buffer: Buffer,
  mimeType: string,
  filename: string
): Promise<string> => {
  // Определяем тип файла
  const extension = filename.split(".").pop()?.toLowerCase();

  // Изображения и PDF
  if (
    mimeType.startsWith("image/") ||
    mimeType === "application/pdf" ||
    extension === "pdf" ||
    ["jpg", "jpeg", "png", "gif", "bmp", "tiff"].includes(extension || "")
  ) {
    return extractTextFromImage(buffer, mimeType);
  }

  // Аудио файлы
  if (
    mimeType.startsWith("audio/") ||
    ["mp3", "wav", "ogg", "m4a", "flac"].includes(extension || "")
  ) {
    return extractTextFromAudio(buffer, mimeType);
  }

  // Видео файлы (извлекаем аудиодорожку)
  if (
    mimeType.startsWith("video/") ||
    ["mp4", "avi", "mov", "mkv", "webm"].includes(extension || "")
  ) {
    // Для видео нужна предварительная обработка для извлечения аудио
    // Здесь упрощенная версия - в реальности нужна библиотека для извлечения аудио из видео
    throw new Error("Video file processing requires additional setup");
  }

  // Документы (DOCX, DOC и т.д.)
  if (
    mimeType.includes("wordprocessingml") ||
    mimeType.includes("msword") ||
    ["docx", "doc"].includes(extension || "")
  ) {
    return extractTextFromDocument(buffer, mimeType);
  }

  throw new Error(`Unsupported file type: ${mimeType}`);
};

