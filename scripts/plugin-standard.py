"""Validate the common maintained-application frontend foundation."""
import json
import importlib.util
from pathlib import Path

VERSIONS = {"react": "19.3.0", "react-dom": "19.3.0", "antd": "6.6.5", "@portal-app/sdk": "*"}


spec = importlib.util.spec_from_file_location("app_authoring", Path(__file__).with_name("app_authoring.py"))
authoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authoring)


def check(root):
    for app in sorted((root / "apps").iterdir()):
        if not app.is_dir():
            continue
        legacy, v2 = app / "app.json", app / "app.v2.json"
        if legacy.exists() and v2.exists():
            raise ValueError(f"{app.name}: cannot declare both legacy and v2 manifests")
        if not legacy.exists() and not v2.exists() and not (app / "frontend").exists():
            continue
        manifest = v2 if v2.exists() else legacy
        authoring.app_folder(root, app.name)
        if not manifest.is_file():
            raise ValueError(f"{app.name}: application manifest is missing")
        declaration = authoring.read_json(manifest)
        if not isinstance(declaration,dict):
            raise ValueError(f"{app.name}: application declaration must be an object")
        experimental = manifest == v2
        if experimental and (declaration.get("format") != "portal.app/v2" or declaration.get("id") != app.name):
            raise ValueError(f"{app.name}: invalid v2 authoring identity")
        frontend = app / "frontend"
        if frontend.is_symlink():
            raise ValueError(f"{app.name}: unsafe frontend directory")
        if experimental:
            authoring.bootstrap(frontend)
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
        foundations = ["AppRoot", "useAppPage", "useAppPresentation", "useAppDraft", "useAppNavigation"] if experimental else ["PortalAppProvider", "PortalPage", "usePortalLocale"]
        for foundation in foundations:
            if foundation not in entry:
                raise ValueError(f"{manifest.parent.name}: shared {foundation} foundation is required")
        if experimental:
            for old in ["PortalAppProvider", "PortalPage", "PortalClient", "PortalLocaleSelect", "usePortalLocale", "createBridgeClient", "window.parent", "document.referrer"]:
                if old in entry:
                    raise ValueError(f"{app.name}: v2 uses AppRoot and the host shell instead of {old}")
        for source in (frontend / "src").rglob("*"):
            if source.is_symlink():
                raise ValueError(f"{app.name}: symlinked frontend source is not supported")
            if source.suffix in {".ts", ".tsx", ".js"}:
                text = source.read_text()
                if any(token in text for token in ["localStorage", "sessionStorage", "document.cookie", "window.parent.postMessage", "parent.postMessage", "fetch(", "XMLHttpRequest"]):
                    raise ValueError(f"{source.relative_to(root)}: use the shared SDK instead of browser authority or a copied bridge")
    return True


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
    print("All maintained application frontends use the common foundation.")
