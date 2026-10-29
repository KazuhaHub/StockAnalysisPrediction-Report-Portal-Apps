// Authoring-only offline preflight; the host still admits exact signed bytes.
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { build } from "vite";
const output = await mkdtemp(join(tmpdir(), "portal-descriptor-check-"));
try {
  if (process.argv.length !== 3) throw new Error();
  await build({
    configFile: false,
    logLevel: "error",
    build: {
      ssr: fileURLToPath(
        new URL("./lib/validate-descriptor-v2.ts", import.meta.url),
      ),
      target: "node24",
      outDir: output,
      rollupOptions: { output: { format: "cjs", entryFileNames: "check.cjs" } },
    },
  });
  execFileSync(process.execPath, [join(output, "check.cjs"), process.argv[2]], {
    stdio: "inherit",
  });
} catch {
  process.exitCode = 1;
} finally {
  await rm(output, { recursive: true, force: true });
}
