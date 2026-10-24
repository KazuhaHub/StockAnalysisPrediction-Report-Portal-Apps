"""Validate the common maintained-application frontend foundation."""
import json
from pathlib import Path

VERSIONS = {"react": "19.3.0", "react-dom": "19.3.0", "antd": "6.6.5", "@portal-app/sdk": "*"}


def check(root):
    for manifest in sorted((root / "apps").glob("*/app.json")):
        frontend = manifest.parent / "frontend"
        package = frontend / "package.json"
        if not package.is_file():
            raise ValueError(f"Missing shared frontend foundation: {package.relative_to(root)}")
        data = json.loads(package.read_text())
        for dependency, version in VERSIONS.items():
            if data.get("dependencies", {}).get(dependency) != version:
                raise ValueError(f"{manifest.parent.name}: {dependency} must use shared version {version}")
        for name in ["tsconfig.json", "vite.config.ts", "src/main.tsx"]:
            if not (frontend / name).is_file():
                raise ValueError(f"{manifest.parent.name}: missing frontend {name}")
        texts = []
        for locale in ["en-US", "zh-CN", "zh-TW"]:
            texts.append(json.loads((frontend / "locales" / f"{locale}.json").read_text()))
        if any(set(value) != set(texts[0]) for value in texts):
            raise ValueError(f"{manifest.parent.name}: locale key mismatch")
        entry = "\n".join(source.read_text() for source in (frontend / "src").rglob("*") if source.suffix in {".ts", ".tsx"})
        if "@portal-app/sdk" not in entry:
            raise ValueError(f"{manifest.parent.name}: shared SDK entry is required")
        for source in (frontend / "src").rglob("*"):
            if source.suffix in {".ts", ".tsx", ".js"}:
                text = source.read_text()
                if any(token in text for token in ["localStorage", "sessionStorage", "document.cookie", "window.parent.postMessage", "parent.postMessage", "fetch(", "XMLHttpRequest"]):
                    raise ValueError(f"{source.relative_to(root)}: use the shared SDK instead of browser authority or a copied bridge")
    return True


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
    print("All maintained application frontends use the common foundation.")
