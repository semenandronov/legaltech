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
  serverExternalPackages: ['pdf-parse', 'mammoth'],
  typescript: {
    ignoreBuildErrors: false,
  },
  reactStrictMode: true,
}

module.exports = nextConfig

