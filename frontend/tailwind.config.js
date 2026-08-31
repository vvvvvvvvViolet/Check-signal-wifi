/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Grade palette - shared with the backend so a colour means the same
        // thing in the UI, the exported PDF and the heatmap canvas.
        grade: {
          excellent: '#16a34a',
          good: '#4ade80',
          fair: '#facc15',
          poor: '#ef4444',
          unknown: '#94a3b8',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
