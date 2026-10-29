import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Django API runs on :8000; Vite proxies /api so cookies and CSRF work same-origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist" },
});
