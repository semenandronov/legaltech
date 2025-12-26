import { createTheme, ThemeOptions } from '@mui/material/styles'
import { PaletteMode } from '@mui/material'

// Harvey-style color palette
const harveyColors = {
  // Primary colors (Harvey blue/purple gradient)
  primary: {
    main: '#3B82F6', // Blue
    light: '#60A5FA',
    dark: '#2563EB',
    contrastText: '#FFFFFF',
  },
  // Secondary colors (Purple accent)
  secondary: {
    main: '#8B5CF6', // Purple
    light: '#A78BFA',
    dark: '#7C3AED',
    contrastText: '#FFFFFF',
  },
  // Success (Green)
  success: {
    main: '#10B981',
    light: '#34D399',
    dark: '#059669',
    contrastText: '#FFFFFF',
  },
  // Warning (Yellow/Orange)
  warning: {
    main: '#F59E0B',
    light: '#FBBF24',
    dark: '#D97706',
    contrastText: '#FFFFFF',
  },
  // Error (Red)
  error: {
    main: '#EF4444',
    light: '#F87171',
    dark: '#DC2626',
    contrastText: '#FFFFFF',
  },
  // Info (Cyan)
  info: {
    main: '#00BDD4',
    light: '#22D3EE',
    dark: '#0891B2',
    contrastText: '#FFFFFF',
  },
}

// Dark theme palette
const darkPalette: ThemeOptions['palette'] = {
  mode: 'dark',
  ...harveyColors,
  background: {
    default: '#0F1419', // Dark background
    paper: '#1A2332', // Card background
  },
  text: {
    primary: '#F5F5F5',
    secondary: '#A0A8B8',
    disabled: '#5A6476',
  },
  divider: '#3A4556',
  // Custom colors for Harvey
  grey: {
    50: '#F5F5F5',
    100: '#E5E7EB',
    200: '#D1D5DB',
    300: '#9CA3AF',
    400: '#6B7280',
    500: '#5A6476',
    600: '#4B5563',
    700: '#3A4556',
    800: '#242F3F',
    900: '#1A2332',
  },
}

// Light theme palette
const lightPalette: ThemeOptions['palette'] = {
  mode: 'light',
  ...harveyColors,
  background: {
    default: '#FFFFFF',
    paper: '#F8F9FA',
  },
  text: {
    primary: '#0F1419',
    secondary: '#666B78',
    disabled: '#B8BCC5',
  },
  divider: '#E5E8EB',
  grey: {
    50: '#F8F9FA',
    100: '#F0F2F5',
    200: '#E5E8EB',
    300: '#D1D5DB',
    400: '#B8BCC5',
    500: '#9CA3AF',
    600: '#666B78',
    700: '#4B5563',
    800: '#374151',
    900: '#0F1419',
  },
}

// Typography (Inter font family)
const typography: ThemeOptions['typography'] = {
  fontFamily: [
    'Inter',
    '-apple-system',
    'BlinkMacSystemFont',
    '"Segoe UI"',
    'Roboto',
    '"Helvetica Neue"',
    'Arial',
    'sans-serif',
  ].join(','),
  h1: {
    fontSize: '32px',
    fontWeight: 600,
    lineHeight: 1.2,
    letterSpacing: '-0.02em',
  },
  h2: {
    fontSize: '24px',
    fontWeight: 600,
    lineHeight: 1.3,
    letterSpacing: '-0.01em',
  },
  h3: {
    fontSize: '20px',
    fontWeight: 600,
    lineHeight: 1.4,
  },
  h4: {
    fontSize: '18px',
    fontWeight: 600,
    lineHeight: 1.4,
  },
  h5: {
    fontSize: '16px',
    fontWeight: 600,
    lineHeight: 1.5,
  },
  h6: {
    fontSize: '14px',
    fontWeight: 600,
    lineHeight: 1.5,
  },
  body1: {
    fontSize: '14px',
    lineHeight: 1.75,
    fontWeight: 400,
  },
  body2: {
    fontSize: '12px',
    lineHeight: 1.5,
    fontWeight: 400,
  },
  button: {
    fontSize: '14px',
    fontWeight: 500,
    textTransform: 'none', // Material-UI uses uppercase by default, we want lowercase
  },
  caption: {
    fontSize: '12px',
    lineHeight: 1.4,
    fontWeight: 400,
  },
  overline: {
    fontSize: '11px',
    lineHeight: 1.4,
    fontWeight: 500,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
}

// Shape (border radius)
const shape: ThemeOptions['shape'] = {
  borderRadius: 8, // Default border radius
}

// Spacing
const spacing = 8 // 8px base unit

// Shadows (Harvey-style subtle shadows)
const shadows = [
  'none',
  '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
  '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)',
  '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
  '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
  '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
  '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
  ...Array(18).fill('none'),
] as ThemeOptions['shadows']

// Transitions
const transitions: ThemeOptions['transitions'] = {
  duration: {
    shortest: 150,
    shorter: 200,
    short: 250,
    standard: 300,
    complex: 375,
    enteringScreen: 225,
    leavingScreen: 195,
  },
  easing: {
    easeInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
    easeOut: 'cubic-bezier(0.0, 0, 0.2, 1)',
    easeIn: 'cubic-bezier(0.4, 0, 1, 1)',
    sharp: 'cubic-bezier(0.4, 0, 0.6, 1)',
  },
}

// Breakpoints
const breakpoints: ThemeOptions['breakpoints'] = {
  values: {
    xs: 0,
    sm: 640,
    md: 768,
    lg: 1024,
    xl: 1280,
    // Custom breakpoint for 2xl screens
    // Note: MUI doesn't support custom breakpoint names directly, but we can use numbers
  },
}

// Create theme function
export const createHarveyTheme = (mode: PaletteMode = 'dark') => {
  const palette = mode === 'dark' ? darkPalette : lightPalette

  return createTheme({
    palette,
    typography,
    shape,
    spacing,
    shadows,
    transitions,
    breakpoints,
    components: {
      // Global component overrides
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            scrollbarWidth: 'thin',
            scrollbarColor: mode === 'dark' ? '#3A4556 #1A2332' : '#D1D5DB #F8F9FA',
            '&::-webkit-scrollbar': {
              width: '8px',
              height: '8px',
            },
            '&::-webkit-scrollbar-track': {
              background: mode === 'dark' ? '#1A2332' : '#F8F9FA',
            },
            '&::-webkit-scrollbar-thumb': {
              background: mode === 'dark' ? '#3A4556' : '#D1D5DB',
              borderRadius: '4px',
              '&:hover': {
                background: mode === 'dark' ? '#4B5563' : '#9CA3AF',
              },
            },
          },
        },
      },
      // Button overrides
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            padding: '8px 16px',
            fontWeight: 500,
            textTransform: 'none',
            boxShadow: 'none',
            '&:hover': {
              boxShadow: 'none',
            },
          },
          contained: {
            '&:hover': {
              boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
            },
          },
        },
      },
      // TextField overrides
      MuiTextField: {
        styleOverrides: {
          root: {
            '& .MuiOutlinedInput-root': {
              borderRadius: 8,
            },
          },
        },
      },
      // Card overrides
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            boxShadow: mode === 'dark' 
              ? '0 1px 3px 0 rgba(0, 0, 0, 0.3)'
              : '0 1px 3px 0 rgba(0, 0, 0, 0.1)',
          },
        },
      },
      // Paper overrides
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      // Chip overrides
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            fontWeight: 500,
          },
        },
      },
      // Drawer overrides
      MuiDrawer: {
        styleOverrides: {
          paper: {
            borderRight: `1px solid ${mode === 'dark' ? '#3A4556' : '#E5E8EB'}`,
          },
        },
      },
      // AppBar overrides
      MuiAppBar: {
        styleOverrides: {
          root: {
            boxShadow: mode === 'dark' 
              ? '0 1px 3px 0 rgba(0, 0, 0, 0.3)'
              : '0 1px 3px 0 rgba(0, 0, 0, 0.1)',
          },
        },
      },
    },
  })
}

// Default export - dark theme
export const harveyTheme = createHarveyTheme('dark')

// Export theme creator for use with theme provider
export default harveyTheme

