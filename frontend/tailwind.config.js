/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Dark Mode Colors
        'bg-primary-dark': '#0F1419',
        'bg-secondary-dark': '#1A2332',
        'bg-tertiary-dark': '#242F3F',
        'border-dark': '#3A4556',
        'text-primary-dark': '#F5F5F5',
        'text-secondary-dark': '#A0A8B8',
        'text-disabled-dark': '#5A6476',
        
        // Light Mode Colors
        'bg-primary-light': '#FFFFFF',
        'bg-secondary-light': '#F8F9FA',
        'bg-tertiary-light': '#F0F2F5',
        'border-light': '#E5E8EB',
        'text-primary-light': '#0F1419',
        'text-secondary-light': '#666B78',
        'text-disabled-light': '#B8BCC5',
        
        // Accent Colors (same for both modes, but can be adjusted)
        primary: {
          DEFAULT: '#0FA3FF',
          dark: '#0FA3FF',
          light: '#0866FF',
        },
        success: {
          DEFAULT: '#28C76F',
          dark: '#28C76F',
          light: '#22AB94',
        },
        warning: {
          DEFAULT: '#FFB547',
          dark: '#FFB547',
          light: '#F59E0B',
        },
        error: {
          DEFAULT: '#FF5370',
          dark: '#FF5370',
          light: '#DC3545',
        },
        info: {
          DEFAULT: '#00BDD4',
          dark: '#00BDD4',
          light: '#0288D1',
        },
        
        // Document Type Colors
        'doc-contract': '#9C27B0',
        'doc-email': '#FF6F00',
        'doc-court': '#D32F2F',
        'doc-sanction': '#880E4F',
        'doc-compliance': '#00838F',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['Fira Code', 'Courier New', 'monospace'],
      },
      fontSize: {
        'h1': ['32px', { lineHeight: '1.2', fontWeight: '600' }],
        'h2': ['24px', { lineHeight: '1.3', fontWeight: '600' }],
        'h3': ['20px', { lineHeight: '1.4', fontWeight: '600' }],
        'body-large': ['16px', { lineHeight: '1.75', fontWeight: '400' }],
        'body': ['14px', { lineHeight: '1.75', fontWeight: '400' }],
        'small': ['12px', { lineHeight: '1.5', fontWeight: '400' }],
        'tiny': ['11px', { lineHeight: '1.4', fontWeight: '400' }],
        'mono': ['13px', { lineHeight: '1.5', fontWeight: '400' }],
      },
      spacing: {
        'xs': '4px',
        'sm': '8px',
        'md': '16px',
        'lg': '24px',
        'xl': '32px',
        '2xl': '48px',
      },
      borderRadius: {
        'DEFAULT': '6px',
        'sm': '4px',
        'md': '6px',
        'lg': '8px',
      },
      boxShadow: {
        'card': '0 2px 8px rgba(0, 0, 0, 0.1)',
        'card-hover': '0 4px 16px rgba(0, 0, 0, 0.15)',
        'focus': '0 0 0 3px rgba(15, 163, 255, 0.3)',
        'focus-light': '0 0 0 3px rgba(8, 102, 255, 0.3)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'fade-out': 'fadeOut 0.2s ease-in-out',
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        fadeOut: {
          '0%': { opacity: '1', transform: 'scale(1)' },
          '100%': { opacity: '0', transform: 'scale(0.95)' },
        },
      },
    },
  },
  plugins: [],
}
