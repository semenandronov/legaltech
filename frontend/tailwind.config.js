/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
  	container: {
  		center: true,
  		padding: '2rem',
  		screens: {
  			'2xl': '1400px'
  		}
  	},
  	extend: {
  		colors: {
  			border: 'hsl(var(--border))',
  			input: 'hsl(var(--input))',
  			ring: 'hsl(var(--ring))',
  			background: 'hsl(var(--background))',
  			foreground: 'hsl(var(--foreground))',
  			primary: {
  				DEFAULT: 'hsl(var(--primary))',
  				foreground: 'hsl(var(--primary-foreground))'
  			},
  			secondary: {
  				DEFAULT: 'hsl(var(--secondary))',
  				foreground: 'hsl(var(--secondary-foreground))'
  			},
  			destructive: {
  				DEFAULT: 'hsl(var(--destructive))',
  				foreground: 'hsl(var(--destructive-foreground))'
  			},
  			muted: {
  				DEFAULT: 'hsl(var(--muted))',
  				foreground: 'hsl(var(--muted-foreground))'
  			},
  			accent: {
  				DEFAULT: 'hsl(var(--accent))',
  				foreground: 'hsl(var(--accent-foreground))'
  			},
  			popover: {
  				DEFAULT: 'hsl(var(--popover))',
  				foreground: 'hsl(var(--popover-foreground))'
  			},
  			card: {
  				DEFAULT: 'hsl(var(--card))',
  				foreground: 'hsl(var(--card-foreground))'
  			},
  			'bg-primary-dark': '#0F1419',
  			'bg-secondary-dark': '#1A2332',
  			'bg-tertiary-dark': '#242F3F',
  			'border-dark': '#3A4556',
  			'text-primary-dark': '#F5F5F5',
  			'text-secondary-dark': '#A0A8B8',
  			'text-disabled-dark': '#5A6476',
  			'bg-primary-light': '#FFFFFF',
  			'bg-secondary-light': '#F8F9FA',
  			'bg-tertiary-light': '#F0F2F5',
  			'border-light': '#E5E8EB',
  			'text-primary-light': '#0F1419',
  			'text-secondary-light': '#666B78',
  			'text-disabled-light': '#B8BCC5',
  			success: {
  				DEFAULT: '#28C76F',
  				dark: '#28C76F',
  				light: '#22AB94'
  			},
  			warning: {
  				DEFAULT: '#FFB547',
  				dark: '#FFB547',
  				light: '#F59E0B'
  			},
  			error: {
  				DEFAULT: '#FF5370',
  				dark: '#FF5370',
  				light: '#DC3545'
  			},
  			info: {
  				DEFAULT: '#00BDD4',
  				dark: '#00BDD4',
  				light: '#0288D1'
  			},
  			'doc-contract': '#9C27B0',
  			'doc-email': '#FF6F00',
  			'doc-court': '#D32F2F',
  			'doc-sanction': '#880E4F',
  			'doc-compliance': '#00838F',
  			sidebar: {
  				DEFAULT: 'hsl(var(--sidebar-background))',
  				foreground: 'hsl(var(--sidebar-foreground))',
  				primary: 'hsl(var(--sidebar-primary))',
  				'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
  				accent: 'hsl(var(--sidebar-accent))',
  				'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
  				border: 'hsl(var(--sidebar-border))',
  				ring: 'hsl(var(--sidebar-ring))'
  			}
  		},
  		fontFamily: {
  			sans: [
  				'Inter',
  				'-apple-system',
  				'BlinkMacSystemFont',
  				'Segoe UI',
  				'Roboto',
  				'sans-serif'
  			],
  			mono: [
  				'Fira Code',
  				'Courier New',
  				'monospace'
  			]
  		},
  		fontSize: {
  			h1: [
  				'32px',
  				{
  					lineHeight: '1.2',
  					fontWeight: '600'
  				}
  			],
  			h2: [
  				'24px',
  				{
  					lineHeight: '1.3',
  					fontWeight: '600'
  				}
  			],
  			h3: [
  				'20px',
  				{
  					lineHeight: '1.4',
  					fontWeight: '600'
  				}
  			],
  			'body-large': [
  				'16px',
  				{
  					lineHeight: '1.75',
  					fontWeight: '400'
  				}
  			],
  			body: [
  				'14px',
  				{
  					lineHeight: '1.75',
  					fontWeight: '400'
  				}
  			],
  			small: [
  				'12px',
  				{
  					lineHeight: '1.5',
  					fontWeight: '400'
  				}
  			],
  			tiny: [
  				'11px',
  				{
  					lineHeight: '1.4',
  					fontWeight: '400'
  				}
  			],
  			mono: [
  				'13px',
  				{
  					lineHeight: '1.5',
  					fontWeight: '400'
  				}
  			]
  		},
  		spacing: {
  			xs: '4px',
  			sm: '8px',
  			md: '16px',
  			lg: '24px',
  			xl: '32px',
  			'2xl': '48px'
  		},
  		borderRadius: {
  			lg: 'var(--radius)',
  			md: 'calc(var(--radius) - 2px)',
  			sm: 'calc(var(--radius) - 4px)',
  			DEFAULT: '6px'
  		},
  		boxShadow: {
  			card: '0 2px 8px rgba(0, 0, 0, 0.1)',
  			'card-hover': '0 4px 16px rgba(0, 0, 0, 0.15)',
  			focus: '0 0 0 3px rgba(15, 163, 255, 0.3)',
  			'focus-light': '0 0 0 3px rgba(8, 102, 255, 0.3)'
  		},
  		keyframes: {
  			'accordion-down': {
  				from: {
  					height: '0'
  				},
  				to: {
  					height: 'var(--radix-accordion-content-height)'
  				}
  			},
  			'accordion-up': {
  				from: {
  					height: 'var(--radix-accordion-content-height)'
  				},
  				to: {
  					height: '0'
  				}
  			},
  			fadeIn: {
  				'0%': {
  					opacity: '0',
  					transform: 'scale(0.95)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'scale(1)'
  				}
  			},
  			fadeOut: {
  				'0%': {
  					opacity: '1',
  					transform: 'scale(1)'
  				},
  				'100%': {
  					opacity: '0',
  					transform: 'scale(0.95)'
  				}
  			}
  		},
  		animation: {
  			'accordion-down': 'accordion-down 0.2s ease-out',
  			'accordion-up': 'accordion-up 0.2s ease-out',
  			'fade-in': 'fadeIn 0.3s ease-in-out',
  			'fade-out': 'fadeOut 0.2s ease-in-out',
  			'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite'
  		}
  	}
  },
  plugins: [],
}
