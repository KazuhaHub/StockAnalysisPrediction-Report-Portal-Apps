"""Build the experimental root as a self-contained classic bundle, without publishing."""
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="portal-root-v2-") as directory:
    target = Path(directory)
    (target / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
    entry = ROOT / "packages/app-sdk/tests/fixtures/root-v2/main.tsx"
    config = target / "vite.config.mjs"
    config.write_text(
        "import {defineConfig} from 'vite';\n"
        "import react from '@vitejs/plugin-react';\n"
        "export default defineConfig({plugins:[react()],"
        "define:{'process.env.NODE_ENV':JSON.stringify('production')},"
        "build:{target:'es2022',cssCodeSplit:false,outDir:"
        + json.dumps(str(target / "dist"))
        + ",lib:{entry:"
        + json.dumps(str(entry))
        + ",name:'PortalRootFixture',formats:['iife'],fileName:()=> 'app.js',cssFileName:'style'}}});\n"
    )
    subprocess.run(
        [str(ROOT / "node_modules/.bin/vite"), "build", "--config", str(config)],
        cwd=ROOT,
        check=True,
    )
    files = sorted(path.name for path in (target / "dist").iterdir())
    if files != ["app.js", "style.css"]:
        raise ValueError(f"Expected one classic bundle and one stylesheet, got {files}")
    source = (target / "dist/app.js").read_text()
    if "portal.app.bridge/2-dev.3" not in source or "portal-v2-root" not in source:
        raise ValueError("Build omitted the experimental presentation root")
    styles = (target / "dist/style.css").read_text()
    if "portal-v2-root" not in styles:
        raise ValueError("Build omitted root layout styles")
    print("Experimental React root builds as one classic script and one local stylesheet.")
