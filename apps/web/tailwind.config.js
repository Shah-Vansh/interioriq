/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        accent: { DEFAULT: '#b45309', light: '#d97706', muted: '#92400e', subtle: '#fef3c7' }
      }
    }
  },
  plugins: []
}
