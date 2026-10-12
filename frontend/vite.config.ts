import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard runs at http://localhost:5173 and calls the Problem 7 FastAPI
// backend at http://localhost:8000 (see src/api.ts). The backend's CORS setting
// allows exactly http://localhost:5173, so the port is pinned: strictPort makes
// Vite stop with an error instead of silently moving to 5174 (which CORS would block).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
  },
});
