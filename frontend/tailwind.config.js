/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        alexa: {
          cyan: "#00c8ff",
          darkCyan: "#0088cc",
          pulse: "#00f0ff",
        },
        amazon: {
          orange: "#ff9900",
          darkOrange: "#e68a00",
          navy: "#131921",
          lightNavy: "#232f3e",
        },
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 15px rgba(0, 200, 255, 0.2)' },
          '100%': { boxShadow: '0 0 30px rgba(0, 200, 255, 0.6)' },
        }
      }
    },
  },
  plugins: [],
}
