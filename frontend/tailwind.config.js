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
  			// Design tokens from design-tokens.css
  			bg: {
  				primary: 'var(--color-bg-primary)',
  				secondary: 'var(--color-bg-secondary)',
  				tertiary: 'var(--color-bg-tertiary)',
  				elevated: 'var(--color-bg-elevated)',
  				hover: 'var(--color-bg-hover)',
  				active: 'var(--color-bg-active)',
  			},
  			text: {
  				primary: 'var(--color-text-primary)',
  				secondary: 'var(--color-text-secondary)',
  				muted: 'var(--color-text-muted)',
  				disabled: 'var(--color-text-disabled)',
  			},
  			border: {
  				DEFAULT: 'var(--color-border)',
  				subtle: 'var(--color-border-subtle)',
  				strong: 'var(--color-border-strong)',
  			},
  			accent: {
  				DEFAULT: 'var(--color-accent)',
  				muted: 'var(--color-accent-muted)',
  				hover: 'var(--color-accent-hover)',
  			},
  			success: {
  				DEFAULT: 'var(--color-success)',
  				bg: 'var(--color-success-bg)',
  			},
  			warning: {
  				DEFAULT: 'var(--color-warning)',
  				bg: 'var(--color-warning-bg)',
  			},
  			error: {
  				DEFAULT: 'var(--color-error)',
  				bg: 'var(--color-error-bg)',
  			},
  			info: {
  				DEFAULT: 'var(--color-info)',
  				bg: 'var(--color-info-bg)',
  			},
  			// shadcn/ui compatibility (keep for existing components)
  			background: 'var(--color-bg-primary)',
  			foreground: 'var(--color-text-primary)',
  			primary: {
  				DEFAULT: 'var(--color-accent)',
  				foreground: 'var(--color-bg-primary)',
  			},
  			secondary: {
  				DEFAULT: 'var(--color-bg-secondary)',
  				foreground: 'var(--color-text-primary)',
  			},
  			muted: {
  				DEFAULT: 'var(--color-bg-tertiary)',
  				foreground: 'var(--color-text-secondary)',
  			},
  			destructive: {
  				DEFAULT: 'var(--color-error)',
  				foreground: 'var(--color-text-primary)',
  			},
  			card: {
  				DEFAULT: 'var(--color-bg-elevated)',
  				foreground: 'var(--color-text-primary)',
  			},
  			popover: {
  				DEFAULT: 'var(--color-bg-elevated)',
  				foreground: 'var(--color-text-primary)',
  			},
  			input: 'var(--color-border)',
  			ring: 'var(--color-border-strong)',
  			// Document type colors (keep for compatibility)
  			'doc-contract': '#9C27B0',
  			'doc-email': '#FF6F00',
  			'doc-court': '#D32F2F',
  			'doc-sanction': '#880E4F',
  			'doc-compliance': '#00838F',
  		},
		fontFamily: {
			sans: [
				'Inter',
				'-apple-system',
				'BlinkMacSystemFont',
				'Segoe UI',
				'sans-serif'
			],
			display: [
				'Cormorant Garamond',
				'Playfair Display',
				'serif'
			],
			mono: [
				'JetBrains Mono',
				'Fira Code',
				'Courier New',
				'monospace'
			],
			body: [
				'Inter',
				'-apple-system',
				'BlinkMacSystemFont',
				'Segoe UI',
				'sans-serif'
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
  			xs: 'var(--space-1)',
  			sm: 'var(--space-2)',
  			md: 'var(--space-4)',
  			lg: 'var(--space-6)',
  			xl: 'var(--space-8)',
  			'2xl': 'var(--space-12)',
  		},
  		borderRadius: {
  			sm: 'var(--radius-sm)',
  			md: 'var(--radius-md)',
  			lg: 'var(--radius-lg)',
  			xl: 'var(--radius-xl)',
  			'2xl': 'var(--radius-2xl)',
  			full: 'var(--radius-full)',
  			DEFAULT: 'var(--radius-md)'
  		},
  		boxShadow: {
  			sm: 'var(--shadow-sm)',
  			md: 'var(--shadow-md)',
  			lg: 'var(--shadow-lg)',
  			xl: 'var(--shadow-xl)',
  			none: 'var(--shadow-none)',
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
  					transform: 'translateY(8px)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'translateY(0)'
  				}
  			},
  			shimmer: {
  				'0%': {
  					backgroundPosition: '-200% 0'
  				},
  				'100%': {
  					backgroundPosition: '200% 0'
  				}
  			}
  		},
  		animation: {
  			'accordion-down': 'accordion-down 0.2s ease-out',
  			'accordion-up': 'accordion-up 0.2s ease-out',
  			'fade-in': 'fadeIn var(--transition-base)',
  			shimmer: 'shimmer 2s linear infinite'
  		}
  	}
  },
  plugins: [],
}
