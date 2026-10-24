import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    target: "es2022",
    cssCodeSplit: false,
    lib: {
      entry: "src/main.tsx",
      name: "StatusApp",
      formats: ["iife"],
      fileName: () => "app.js",
      cssFileName: "style",
    },
  },
});
