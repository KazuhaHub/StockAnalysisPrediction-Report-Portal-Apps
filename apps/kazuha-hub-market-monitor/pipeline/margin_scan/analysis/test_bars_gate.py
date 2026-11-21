#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线验证 fetch_bars 的覆盖率闸门 / 原子写入 / 盘中K线剔除。

不发任何网络请求：mock 掉 _fetch_bars_one，在临时目录里跑真实 fetch_bars。
用法：python3 analysis/test_bars_gate.py
"""
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fetch_data as fd  # noqa: E402

COLS = ["code", "date", "open", "close", "high", "low", "volume", "amount"]


def rec(code, date, close=10.0):
    return (code, date, close, close, close, close, 1000.0, 1000.0)


def old_table():
    rows = [rec(c, d) for d in ("2026-11-09", "2026-11-10") for c in "ABC"]
    return pd.DataFrame(rows, columns=COLS)


def case(name, mock_fn, codes="ABC"):
    tmp = Path(tempfile.mkdtemp(prefix="barsgate_"))
    fd.DATA = tmp
    old_table().to_parquet(tmp / "bars.parquet", index=False)
    try:
        with patch.object(fd, "_fetch_bars_one", side_effect=mock_fn):
            out = fd.fetch_bars(list(codes), refresh=True, end_date="20261111")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check(label, cond, detail=""):
    print("  %s %s %s" % ("PASS" if cond else "FAIL", label, detail))
    return bool(cond)


def main():
    ok = []

    # 1) 全成功：闸门应通过，新数据成为权威，历史不丢
    def all_ok(code, retry=2, end_date=None):
        return [rec(code, "2026-11-11", 11.0), rec(code, "2026-11-12", 99.0)]
    print("[1] 全量成功 + 混入 11-12 盘中K线")
    out = case("all", all_ok)
    hist = out[out["date"].isin(["2026-11-09", "2026-11-10"])]
    ok.append(check("旧表历史完整(6行)", len(hist) == 6, "实际 %d" % len(hist)))
    ok.append(check("11-11 覆盖 3 只", out[out.date == "2026-11-11"].code.nunique() == 3))
    ok.append(check("11-12 盘中K线被剔除", "2026-11-12" not in set(out.date)))
    ok.append(check("新数据生效(11-11 close=11)",
                    (out[out.date == "2026-11-11"].close == 11.0).all()))

    # 2) 部分成功（1/3，远低于 98%）：闸门不通过，旧表为权威
    def partial(code, retry=2, end_date=None):
        return [rec(code, "2026-11-11", 11.0)] if code == "A" else None
    print("[2] 仅 1/3 成功（模拟限流丢数）")
    out = case("partial", partial)
    hist = out[out["date"].isin(["2026-11-09", "2026-11-10"])]
    ok.append(check("旧表历史完整(6行)", len(hist) == 6, "实际 %d" % len(hist)))
    ok.append(check("旧表价格未被覆盖(hist close=10)",
                    (hist.close == 10.0).all()))
    ok.append(check("仅补入 A 的 11-11 行",
                    set(out[out.date == "2026-11-11"].code) == {"A"}))

    # 3) 全失败：旧表应原封不动
    def none_ok(code, retry=2, end_date=None):
        return None
    print("[3] 全部抓取失败")
    out = case("none", none_ok)
    ok.append(check("旧表完全不变(6行/close=10/无11-11)",
                    len(out) == 6 and (out.close == 10.0).all()
                    and "2026-11-11" not in set(out.date),
                    "实际 %d 行" % len(out)))

    # 4) 非 refresh 只补缺失票
    def all_ok2(code, retry=2, end_date=None):
        return [rec(code, "2026-11-11", 11.0)]
    print("[4] 非 refresh 模式")
    tmp = Path(tempfile.mkdtemp(prefix="barsgate_"))
    fd.DATA = tmp
    old_table().to_parquet(tmp / "bars.parquet", index=False)
    try:
        with patch.object(fd, "_fetch_bars_one", side_effect=all_ok2) as m:
            out = fd.fetch_bars(["A", "B", "C", "D"], refresh=False,
                                end_date="20261111")
        ok.append(check("只抓缺失的 1 只", m.call_count == 1,
                        "实际调用 %d 次" % m.call_count))
        ok.append(check("D 的 11-11 已补入", "D" in set(out[out.date == "2026-11-11"].code)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：%d/%d 通过" % (sum(ok), len(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
