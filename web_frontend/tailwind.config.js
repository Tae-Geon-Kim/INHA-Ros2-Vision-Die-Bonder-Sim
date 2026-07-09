/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#202822",
        field: "#f6f7f4",
        moss: "#267a4d",
        ember: "#a83b3b",
        signal: "#376d86",
      },
      boxShadow: {
        panel: "0 18px 48px rgba(31, 42, 35, 0.10)",
      },
    },
  },
  plugins: [],
};
