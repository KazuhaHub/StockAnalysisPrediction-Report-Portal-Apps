import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.tsx"],
    setupFiles: ["tests/setup.ts"],
    // Above asyncUtilTimeout (tests/setup.ts), so a wait that runs out reports its own error.
    testTimeout: 15000,
  },
});
