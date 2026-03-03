import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Brand Guidelines v1.0 — exact values
        teal: {
          DEFAULT: '#0E3D3F',
          light: '#E8F0F0',   // light teal — cards, sections
        },
        copper: {
          DEFAULT: '#C27840',
          light: '#F5E6D5',   // light copper — badges, highlights
        },
        cream: '#FDF8F0',
        'off-white': '#F7F7F7',
        'near-black': '#1A1A1A',
        'mid-grey': '#666666',
        'light-grey': '#999999',
      },
      fontFamily: {
        // Brand Guidelines §4.2 — web font stack
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
        mono: ['"JetBrains Mono"', 'Consolas', '"Courier New"', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
