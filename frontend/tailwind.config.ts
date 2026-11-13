import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        midnight: "#080D18",
        slatepanel: "#111827",
        cyan: "#00E5FF",
        ai: "#3B82F6",
        emergency: "#FF3B5C",
        soft: "#F8FAFC",
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
        display: ["Space Grotesk", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      boxShadow: {
        glow: "0 0 34px rgba(0,229,255,.12)",
      },
    },
  },
  plugins: [],
};
export default config;
