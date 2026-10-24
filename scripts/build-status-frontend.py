"""Build a self-contained classic-script app compatible with a null-origin iframe."""
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "apps" / "status" / "frontend"
locales = {name: json.loads((root / "locales" / f"{name}.json").read_text()) for name in ["en-US", "zh-CN", "zh-TW"]}
keys = set(locales["en-US"])
if any(set(value) != keys for value in locales.values()):
    raise ValueError("Status locale keys differ")
output = root / "dist"
output.mkdir(parents=True, exist_ok=True)
for name in ["index.html", "style.css"]:
    shutil.copyfile(root / "src" / name, output / name)
source = "const STATUS_LOCALES = " + json.dumps(locales, ensure_ascii=False) + ";\n"
source += (root / "src" / "contracts.cjs").read_text() + ";\n"
source += (root / "src" / "app.js").read_text()
(output / "app.js").write_text(source)

public = root.parents[0] / "service" / "internal" / "status" / "public"
public.mkdir(parents=True, exist_ok=True)
for name in ["index.html", "style.css"]:
    shutil.copyfile(root / "src" / name, public / name)
(public / "app.js").write_text("const STATUS_LOCALES = " + json.dumps(locales, ensure_ascii=False) + ";\n" + (root / "src" / "contracts.cjs").read_text() + ";\n" + (root / "public-src" / "app.js").read_text())
