// DEVELOPMENT ONLY: serves the app inside a stand-in Portal host page with a
// mock backend. The production build uses vite.config.ts and never reads dev/.
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { mockBackendPlugin } from "./dev/mock-backend.mjs";

const snapshotDir = process.env.MM_SNAPSHOT_DIR;
if (!snapshotDir)
  throw new Error(
    "Set MM_SNAPSHOT_DIR to a directory of <module>/<YYYY-MM-DD>.json snapshots",
  );

export default defineConfig({
  root: import.meta.dirname,
  plugins: [react(), mockBackendPlugin(resolve(snapshotDir))],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // The app frame is sandboxed without allow-same-origin, so its module
    // requests carry `Origin: null`; allow only that origin, not every site.
    cors: { origin: "null" },
  },
});
