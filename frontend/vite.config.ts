import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발: npm run dev → http://localhost:5173 (API는 백엔드 8000으로 프록시)
// 데모: npm run build:demo → 서버 없이 브라우저 안에서 도는 단일 HTML (dist-demo/)
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: {
    outDir: mode === "demo" ? "dist-demo" : "dist",
    assetsInlineLimit: mode === "demo" ? 100_000_000 : 4096,
    cssCodeSplit: mode !== "demo",
    rollupOptions: mode === "demo" ? { output: { inlineDynamicImports: true } } : {},
  },
}));
