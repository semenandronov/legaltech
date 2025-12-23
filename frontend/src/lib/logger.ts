/**
 * Production-ready logger utility
 * Only logs in development mode
 */

const isDevelopment = import.meta.env.DEV

export const logger = {
  log: (...args: unknown[]) => {
    if (isDevelopment) {
      console.log(...args)
    }
  },
  error: (...args: unknown[]) => {
    // Always log errors, but in production we might want to send them to a service
    if (isDevelopment) {
      console.error(...args)
    } else {
      // In production, you might want to send errors to a logging service
      // For now, we'll still log them but they won't appear in console
      console.error(...args)
    }
  },
  warn: (...args: unknown[]) => {
    if (isDevelopment) {
      console.warn(...args)
    }
  },
  debug: (...args: unknown[]) => {
    if (isDevelopment) {
      console.debug(...args)
    }
  },
  info: (...args: unknown[]) => {
    if (isDevelopment) {
      console.info(...args)
    }
  },
}




