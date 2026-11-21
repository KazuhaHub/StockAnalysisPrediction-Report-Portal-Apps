#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_report.py — 把 HTML 报告构建成「单文件·完全离线」并做静态体检。

解决的问题（一次性）：
  1. 引 CDN → 断网/被墙时图表全白。本脚本把 echarts / mermaid / chart-boot 直接内联进 HTML。
  2. 内联 <script> 有一处括号失配 → 整块 SyntaxError，该页所有图表全不渲染。
     本脚本用 node --check 逐块 + 整体校验。
  3. 图表容器没写死高度 / id 拼错 / getElementById 指向不存在的元素 → 空白不报错。
     本脚本做容器、id、高度三项交叉检查。
  4. 残留任何外链资源 → 离线打开即失效。本脚本在构建后扫描并报错。

用法：
  python3 build_report.py in.html                     # 输出 in.html（先备份为 in.html.bak）
  python3 build_report.py in.html out.html            # 输出到 out.html
  python3 build_report.py in.html --check             # 只体检，不改文件

退出码：0 全部通过（可能含警告）；1 有错误。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(SKILL_DIR, "assets", "js")

# 名称关键字 -> (资产文件名, 内联标记)
LIBS = [
    ("chart-boot", ("chart-boot.js", "chart-boot")),
    ("echarts", ("echarts.min.js", "echarts")),
    ("mermaid", ("mermaid.min.js", "mermaid")),
]

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I)
HEIGHT_RULE_RE = re.compile(
    r"([^{}]+)\{([^{}]*?height\s*:\s*([0-9.]+)\s*(px|vh|rem|em)[^{}]*?)\}", re.I
)

OK = "\033[32m✓\033[0m"
WARN = "\033[33m!\033[0m"
BAD = "\033[31m✗\033[0m"


def find_node() -> str | None:
    for cand in (
        os.path.expanduser("~/.workbuddy/binaries/node/versions/22.22.2-6/bin/node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which("node")


def pick_lib(src: str):
    low = src.lower()
    for key, (fname, tag) in LIBS:
        if key in low:
            return fname, tag
    return None, None


def inline_scripts(html: str, base_dirs: list[str], notes: list):
    """把 <script src> 换成内联内容。返回 (新 html, 已内联库集合)。"""
    inlined = set()

    def repl(m: re.Match) -> str:
        attrs, body = m.group(1), m.group(2)
        if body.strip():
            return m.group(0)
        src_m = SRC_RE.search(attrs)
        if not src_m:
            return m.group(0)
        src = src_m.group(1).strip()

        fname, tag = pick_lib(src)
        content = None
        origin = None

        if fname:
            path = os.path.join(ASSET_DIR, fname)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                origin = path

        if content is None and not re.match(r"^(https?:)?//", src):
            for d in base_dirs:
                path = os.path.normpath(os.path.join(d, src.lstrip("./")))
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                    origin = path
                    break

        if content is None:
            notes.append((BAD, f"无法内联脚本：{src}（本地资产里找不到对应文件）"))
            return m.group(0)

        if "</script" in content.lower():
            notes.append((BAD, f"{origin} 含 </script 字面量，不能直接内联"))
            return m.group(0)

        inlined.add(tag or src)
        notes.append((OK, f"内联 {os.path.basename(origin)} ← {src}"))
        marker = f"/* __INLINED:{tag or 'lib'}__ */\n"
        return "<script>" + marker + content + "\n</script>"

    new = SCRIPT_RE.sub(repl, html)
    return new, inlined


def scan_external(html: str) -> list[tuple[str, str]]:
    """只扫资源型外链，不误伤 <a href> 的引用链接。"""
    pats = [
        (r"<script\b[^>]*\bsrc\s*=\s*[\"'](https?:)?//[^\"']+", "script src"),
        (r"<link\b[^>]*\bhref\s*=\s*[\"'](https?:)?//[^\"']+", "link href"),
        (r"<img\b[^>]*\bsrc\s*=\s*[\"'](https?:)?//[^\"']+", "img src"),
        (r"url\(\s*[\"']?(https?:)?//", "css url()"),
        (r"@import\s+(?:url\()?\s*[\"']?(https?:)?//", "css @import"),
    ]
    out = []
    for pat, label in pats:
        for m in re.finditer(pat, html, re.I):
            snippet = re.sub(r"\s+", " ", m.group(0))[:110]
            out.append((label, snippet))
    return out


def check_js(html: str, node: str) -> list[tuple[str, str]]:
    notes = []
    blocks = []
    for m in SCRIPT_RE.finditer(html):
        attrs, body = m.group(1), m.group(2)
        if SRC_RE.search(attrs) or not body.strip():
            continue
        blocks.append(body)
    if not blocks:
        return notes

    # 逐块校验（跳过内联的大库，只为给应用代码精确定位）
    for i, body in enumerate(blocks, 1):
        if body.lstrip().startswith("/* __INLINED:"):
            continue
        _node_check(node, body, f"内联脚本块 #{i}", notes)

    _node_check(node, "\n;\n".join(blocks), "全部脚本合并", notes)
    return notes


def _node_check(node: str, code: str, label: str, notes: list):
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        res = subprocess.run(
            [node, "--check", path], capture_output=True, text=True, timeout=120
        )
        if res.returncode == 0:
            notes.append((OK, f"JS 语法 {label}"))
        else:
            err = (res.stderr or "").strip().splitlines()
            first = next((l.strip() for l in err if "Error" in l), err[0] if err else "unknown")
            notes.append((BAD, f"JS 语法 {label}：{first}"))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.S | re.I)
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
INLINED_BLOCK_RE = re.compile(
    r"<script>\s*/\* __INLINED:[^*]*\*/.*?</script\s*>", re.S | re.I
)


def strip_inlined(html: str) -> str:
    """去掉已内联的第三方库，只留报告自己的 HTML / CSS / JS，避免库里的字符串干扰检查。"""
    return INLINED_BLOCK_RE.sub("", html)


def _css_rules(html: str):
    """从 <style> 里抽 (selector, px 值, 单位)，区分 height 与 min-height。"""
    rules = []
    for sm in STYLE_RE.finditer(html):
        css = re.sub(r"/\*.*?\*/", "", sm.group(1), flags=re.S)
        for rm in CSS_RULE_RE.finditer(css):
            sel = re.sub(r"\s+", " ", rm.group(1)).strip()
            if not sel or sel.startswith("@"):
                continue
            body = rm.group(2)
            hm = re.search(r"(?<![-\w])height\s*:\s*([0-9.]+)\s*(px|vh|rem|em)", body)
            kind = "height"
            if not hm:
                hm = re.search(r"(?<![-\w])min-height\s*:\s*([0-9.]+)\s*(px|vh|rem|em)", body)
                kind = "min-height"
            if hm:
                rules.append((sel, float(hm.group(1)), hm.group(2), kind))
    return rules


def _selector_hits(sel: str, cid: str, classes: list[str]) -> bool:
    for part in sel.split(","):
        part = part.strip()
        if not part:
            continue
        if re.search(r"#" + re.escape(cid) + r"(?![-_\w])", part):
            return True
        for c in classes:
            if c and re.search(r"\." + re.escape(c) + r"(?![-_\w])", part):
                return True
    return False


def check_containers(html: str) -> list[tuple[str, str]]:
    notes = []
    core = strip_inlined(html)
    ids = set(re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", core))

    containers = []
    for m in re.finditer(r"<(\w+)([^>]*)>", core):
        attrs = m.group(2)
        id_m = re.search(r"""\bid\s*=\s*["']([^"']+)["']""", attrs)
        if not id_m:
            continue
        cid = id_m.group(1)
        cls_m = re.search(r"""\bclass\s*=\s*["']([^"']*)["']""", attrs)
        classes = (cls_m.group(1) if cls_m else "").split()
        if "chart" in classes or re.match(r"^(chart|kline|fig)", cid):
            containers.append((cid, attrs, classes))

    if not containers:
        notes.append((WARN, "没有识别到图表容器（class 含 chart 的元素）"))
    else:
        notes.append((OK, f"识别到 {len(containers)} 个图表容器"))

    rules = _css_rules(core)

    for cid, attrs, classes in containers:
        h = None
        style_m = re.search(r"""style\s*=\s*["']([^"']*)["']""", attrs)
        if style_m:
            hm = re.search(r"(?<![-\w])height\s*:\s*([0-9.]+)\s*(px|vh|rem|em)",
                           style_m.group(1), re.I)
            if hm:
                h = (float(hm.group(1)), hm.group(2))
            else:
                hm = re.search(r"min-height\s*:\s*([0-9.]+)\s*(px|vh|rem|em)",
                               style_m.group(1), re.I)
                if hm:
                    h = (float(hm.group(1)), hm.group(2))
        if h is None:
            for sel, val, unit, _kind in rules:
                if _selector_hits(sel, cid, classes):
                    h = (val, unit)
                    break
        if h is None:
            notes.append((BAD, f"#{cid} 没有显式高度（clientHeight 为 0，画布是空的）"))
        elif h[0] <= 0:
            notes.append((BAD, f"#{cid} 高度为 0"))

    refs = set(re.findall(r"""getElementById\(\s*["']([^"']+)["']\s*\)""", core))
    missing = sorted(r for r in refs if r not in ids)
    if missing:
        notes.append((BAD, "getElementById 指向不存在的 id：" + ", ".join(missing)))
    elif refs:
        notes.append((OK, f"{len(refs)} 个 getElementById 引用全部命中"))

    raw_init = len(re.findall(r"echarts\s*\.\s*init\s*\(", core))
    boot_init = len(re.findall(r"\bCHART\s*\(", core))
    if raw_init:
        notes.append((WARN, f"{raw_init} 处直接调用 echarts.init()，建议改用 CHART()，"
                           "否则单个 option 出错会连带后面全挂"))
    if boot_init:
        notes.append((OK, f"{boot_init} 处图表通过 CHART() 挂载（单图隔离）"))
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--check", action="store_true", help="只体检，不写文件")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    src_path = os.path.abspath(args.input)
    if not os.path.isfile(src_path):
        print(f"找不到文件：{src_path}")
        return 1

    with open(src_path, encoding="utf-8") as f:
        html = f.read()

    notes: list[tuple[str, str]] = []
    base_dirs = [os.path.dirname(src_path), ASSET_DIR]

    t0 = time.time()
    html2, inlined = inline_scripts(html, base_dirs, notes)

    errors = 0
    node = find_node()
    if node:
        notes.extend(check_js(html2, node))
    else:
        notes.append((WARN, "找不到 node，跳过 JS 语法校验（风险：语法错会导致全图不渲染）"))

    notes.extend(check_containers(html2))

    ext = scan_external(html2)
    if ext:
        for label, snip in ext:
            notes.append((BAD, f"残留外链 {label}：{snip}"))
    else:
        notes.append((OK, "无任何外链资源，可完全离线打开"))

    has_echarts = ("echarts" in inlined) or bool(re.search(r"__INLINED:echarts", html2))
    if not has_echarts and re.search(r"\bCHART\s*\(|echarts\s*\.\s*init\s*\(", html2):
        notes.append((BAD, "页面有图表代码但没有内联 echarts"))

    for level, msg in notes:
        if level == BAD:
            errors += 1
        if not args.quiet or level == BAD:
            print(f"  {level} {msg}")

    if args.check:
        print(f"\n体检完成：{errors} 个错误")
        return 1 if errors else 0

    if errors:
        print(f"\n{errors} 个错误，已中止写入（原文件未改动）。")
        return 1

    out_path = os.path.abspath(args.output) if args.output else src_path
    if out_path == src_path:
        backup = src_path + ".bak"
        shutil.copyfile(src_path, backup)
        print(f"  {OK} 原文件已备份到 {os.path.basename(backup)}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html2)

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"\n构建完成 -> {out_path}  ({size_mb:.2f} MB, {time.time() - t0:.1f}s)")
    print(f"错误 {errors} 个。{'✅ 可以交付' if errors == 0 else '❌ 先修上面的错误'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
