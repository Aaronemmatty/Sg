import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // SG Trading brand palette — deep navy terminal meets warm amber accent
        background: "#0A0E1A",
        surface: "#111827",
        "surface-2": "#1A2235",
        "surface-3": "#1F2D45",
        border: "#1E2D45",
        "border-strong": "#2A3F5F",

        // Accent: amber/gold for trading context (P&L positive, actions)
        accent: {
          DEFAULT: "#F59E0B",
          dim: "#B45309",
          glow: "#FCD34D",
        },

        // Semantic
        bull: "#10B981",   // green — profit, long, buy
        bear: "#EF4444",   // red   — loss, short, sell
        neutral: "#6B7280",
        warning: "#F59E0B",

        // Text hierarchy
        text: {
          primary: "#F1F5F9",
          secondary: "#94A3B8",
          muted: "#475569",
          inverse: "#0A0E1A",
        },
      },
      fontFamily: {
        sans: ["'Inter'", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "'Fira Code'", "monospace"],
        display: ["'Inter'", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.65rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "8px",
        lg: "12px",
        xl: "16px",
      },
      backgroundImage: {
        "grid-pattern": "linear-gradient(rgba(30,45,69,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(30,45,69,0.3) 1px, transparent 1px)",
      },
      backgroundSize: {
        "grid-sm": "20px 20px",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-in": "slideIn 0.2s ease-out",
        "ticker": "ticker 30s linear infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideIn: {
          "0%": { opacity: "0", transform: "translateX(-8px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        ticker: {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(-100%)" },
        },
      },
      boxShadow: {
        "glow-accent": "0 0 20px rgba(245,158,11,0.15)",
        "glow-bull": "0 0 20px rgba(16,185,129,0.15)",
        "glow-bear": "0 0 20px rgba(239,68,68,0.15)",
        card: "0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};

export default config;
