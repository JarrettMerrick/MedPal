/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#0052D9',
          light: '#366EF4',
          lighter: '#D9E1FF',
        },
      },
      fontFamily: {
        sans: ['PingFang SC', 'Microsoft YaHei', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

