/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app.vue',
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.{js,ts}',
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#050606',
          900: '#101314',
          800: '#1d2324',
          700: '#2c3435',
          600: '#434c4d',
          500: '#5d6667',
          400: '#7b8687',
        },
        mist: {
          50: '#f4f3f0',
          100: '#e6e2db',
          200: '#d2c9bc',
        },
        ember: {
          400: '#e69c69',
          500: '#d37f4c',
          600: '#b76538',
        },
        ocean: {
          400: '#5ea7b4',
          500: '#4b8f9b',
          600: '#3b717b',
        },
      },
      fontFamily: {
        display: ['"Merriweather"', '"Georgia"', 'serif'],
        body: ['"Merriweather"', '"Georgia"', 'serif'],
      },
      boxShadow: {
        glow: '0 12px 40px rgba(12, 14, 18, 0.45)',
        soft: '0 18px 40px rgba(17, 14, 10, 0.08)',
      },
      backgroundImage: {
        noise:
          'repeating-linear-gradient(0deg, rgba(255,255,255,0.02) 0, rgba(255,255,255,0.02) 1px, transparent 1px, transparent 3px)',
      },
    },
  },
  plugins: [],
}
