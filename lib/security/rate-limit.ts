// Простая реализация rate limiting в памяти
// В продакшене следует использовать Redis или другой внешний сервис

const requestCounts = new Map<string, { count: number; resetTime: number }>();

export const rateLimit = (
  identifier: string,
  maxRequests: number = 10,
  windowMs: number = 60000 // 1 минута
): { allowed: boolean; remaining: number; resetTime: number } => {
  const now = Date.now();
  const record = requestCounts.get(identifier);

  if (!record || now > record.resetTime) {
    // Создаем новую запись
    requestCounts.set(identifier, {
      count: 1,
      resetTime: now + windowMs,
    });
    return {
      allowed: true,
      remaining: maxRequests - 1,
      resetTime: now + windowMs,
    };
  }

  if (record.count >= maxRequests) {
    return {
      allowed: false,
      remaining: 0,
      resetTime: record.resetTime,
    };
  }

  record.count++;
  return {
    allowed: true,
    remaining: maxRequests - record.count,
    resetTime: record.resetTime,
  };
};

// Очистка старых записей (вызывать периодически)
export const cleanupRateLimit = () => {
  const now = Date.now();
  for (const [key, value] of requestCounts.entries()) {
    if (now > value.resetTime) {
      requestCounts.delete(key);
    }
  }
};

// Запускаем очистку каждые 5 минут
if (typeof setInterval !== "undefined") {
  setInterval(cleanupRateLimit, 5 * 60 * 1000);
}

