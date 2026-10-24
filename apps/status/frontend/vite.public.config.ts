import { defineConfig, mergeConfig } from "vite";
import base from "./vite.config.ts";
export default mergeConfig(base, defineConfig({build: {outDir: "../service/internal/status/public", emptyOutDir: true, lib: {entry: "public-src/main.tsx", name: "PublicStatusApp"}}}));
