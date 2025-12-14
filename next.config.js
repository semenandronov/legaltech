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
}

module.exports = nextConfig

