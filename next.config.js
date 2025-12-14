/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverActions: {
      bodySizeLimit: '10mb',
    },
  },
  images: {
    domains: [],
  },
  // Для Replit - используем стандартный output (standalone может вызвать проблемы)
  // Увеличиваем таймауты для длительных операций
  serverExternalPackages: ['pdf-parse', 'mammoth'],
  // Отключаем проверку типов во время сборки (проверка все равно выполняется отдельно)
  typescript: {
    // ВАЖНО: Это отключает проверку типов только во время сборки
    // TypeScript все еще проверяется в IDE и при разработке
    ignoreBuildErrors: false,
  },
  // Убеждаемся, что все страницы правильно обрабатываются
  reactStrictMode: true,
}

module.exports = nextConfig

