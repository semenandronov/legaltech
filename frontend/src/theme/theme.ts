import { createTheme, ThemeOptions } from '@mui/material/styles'
import { PaletteMode } from '@mui/material'

const displayFont = '"Instrument Serif", Georgia, "Times New Roman", serif'

// Палитра в духе Legora: графит, тёплые нейтрали
const harveyColors = {
  primary: {
    main: '#1a1917',
    light: '#3d3a36',
    dark: '#0e0e0d',
    contrastText: '#f8f7f4',
  },
  secondary: {
    main: '#5c5852',
    light: '#7a756d',
    dark: '#3d3a36',
    contrastText: '#f8f7f4',
  },
  success: {
    main: '#3d5c45',
    light: '#5a7a62',
    dark: '#2c422f',
    contrastText: '#f8f7f4',
  },
  warning: {
    main: '#8a5f2b',
    light: '#a67a45',
    dark: '#6b481f',
    contrastText: '#f8f7f4',
  },
  error: {
    main: '#b03a32',
    light: '#c85a4a',
    dark: '#8a2e28',
    contrastText: '#f8f7f4',
  },
  info: {
    main: '#2f4f6f',
    light: '#4a6b8c',
    dark: '#243d56',
    contrastText: '#f8f7f4',
  },
}

const darkPalette: ThemeOptions['palette'] = {
  mode: 'dark',
  ...harveyColors,
  background: {
    default: '#1a1917',
    paper: '#242220',
  },
  text: {
    primary: '#f4f3f0',
    secondary: '#c4c0b8',
    disabled: '#7a756d',
  },
  divider: '#3d3a36',
  grey: {
    50: '#f4f3f0',
    100: '#e4e2dc',
    200: '#cfc9c0',
    300: '#a39e96',
    400: '#7a756d',
    500: '#5c5852',
    600: '#4a4844',
    700: '#3d3a36',
    800: '#2a2826',
    900: '#1a1917',
  },
}

// Light theme palette
const lightPalette: ThemeOptions['palette'] = {
  mode: 'light',
  ...harveyColors,
  background: {
    default: '#f4f3f0',
    paper: '#ffffff',
  },
  text: {
    primary: '#131210',
    secondary: '#4a4844',
    disabled: '#a39e96',
  },
  divider: '#ded9d1',
  grey: {
    50: '#faf9f6',
    100: '#f0efe9',
    200: '#e4e2dc',
    300: '#cfc9c0',
    400: '#a39e96',
    500: '#7a756d',
    600: '#5c5852',
    700: '#4a4844',
    800: '#3d3a36',
    900: '#131210',
  },
}

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
    fontFamily: displayFont,
    fontSize: '32px',
    fontWeight: 400,
    lineHeight: 1.2,
    letterSpacing: '-0.02em',
  },
  h2: {
    fontFamily: displayFont,
    fontSize: '24px',
    fontWeight: 400,
    lineHeight: 1.3,
    letterSpacing: '-0.02em',
  },
  h3: {
    fontFamily: displayFont,
    fontSize: '20px',
    fontWeight: 400,
    lineHeight: 1.35,
    letterSpacing: '-0.02em',
  },
  h4: {
    fontFamily: displayFont,
    fontSize: '18px',
    fontWeight: 400,
    lineHeight: 1.4,
    letterSpacing: '-0.01em',
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
            scrollbarColor: mode === 'dark' ? '#4a4844 #1a1917' : '#cfc9c0 #ebe8e2',
            '&::-webkit-scrollbar': {
              width: '8px',
              height: '8px',
            },
            '&::-webkit-scrollbar-track': {
              background: mode === 'dark' ? '#1a1917' : '#ebe8e2',
            },
            '&::-webkit-scrollbar-thumb': {
              background: mode === 'dark' ? '#4a4844' : '#cfc9c0',
              borderRadius: '4px',
              '&:hover': {
                background: mode === 'dark' ? '#5c5852' : '#a39e96',
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
            borderRight: `1px solid ${mode === 'dark' ? '#3d3a36' : '#ded9d1'}`,
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

