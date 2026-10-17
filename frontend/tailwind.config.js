/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: '#F8F7F4',
        surface: '#FFFFFF',
        ink: {
          DEFAULT: '#252923',
          muted: '#6F746D',
          subtle: '#9A9F98',
        },
        accent: {
          DEFAULT: '#356B52',
          hover: '#28533F',
          light: '#EAF1E9',
        },
        line: {
          DEFAULT: '#E7E5DF',
          dark: '#D8D5CD',
        },
        warn: {
          DEFAULT: '#B7791F',
          light: '#FEF9EE',
          border: '#F2D492',
          text: '#8F5B10',
        },
        danger: {
          DEFAULT: '#C53030',
          hover: '#9B2C2C',
          light: '#FDF2F2',
          border: '#F8B4B4',
          text: '#9B1C1C',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgba(0, 0, 0, 0.04)',
      },
    },
  },
  plugins: [],
}
