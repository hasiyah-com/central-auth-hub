/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#edfffb",
          100: "#cffbf2",
          500: "#34e8c4",
          600: "#13b89a",
          700: "#0d8b75",
          900: "#075043",
        },
        ink: {
          50: "#f7f8fa",
          100: "#eef1f5",
          200: "#dfe5ed",
          300: "#c7d0dc",
          400: "#8e9cb0",
          500: "#68778c",
          600: "#4a586b",
          700: "#303c4d",
          800: "#182131",
          900: "#0a0e17",
        },
      },
      fontFamily: {
        sans: ["IBM Plex Sans Thai", "Noto Sans Thai", "system-ui", "sans-serif"],
        display: ["Anuphan", "IBM Plex Sans Thai", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
