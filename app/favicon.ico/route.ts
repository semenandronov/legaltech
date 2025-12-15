import { NextResponse } from 'next/server';

// Обработчик для favicon.ico - редирект на SVG иконку
export async function GET() {
  // Возвращаем 204 No Content, чтобы браузер не показывал ошибку
  // Next.js автоматически обработает app/icon.svg
  return new NextResponse(null, {
    status: 204,
    headers: {
      'Content-Type': 'image/x-icon',
    },
  });
}

