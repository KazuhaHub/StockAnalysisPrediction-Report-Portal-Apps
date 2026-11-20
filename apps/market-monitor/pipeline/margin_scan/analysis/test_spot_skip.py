#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证核心承诺：底表存在时，日更的 fetch_spot 完全不请求东财 clist。

mock 掉 akshare，在临时目录里跑真实 fetch_spot。
用法：python3 analysis/test_spot_skip.py
"""
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import akshare as ak  # noqa: E402
import fetch_data as fd  # noqa: E402

COLS = ["code", "name", "price", "chg", "amount", "turn", "tcap", "fcap"]
ok = []


def check(label, cond):
    print("  %s %s" % ("PASS" if cond else "FAIL", label))
    ok.append(bool(cond))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="spot_"))
    fd.DATA = tmp
    pd.DataFrame([{
        "code": "600519", "name": "缓存名称", "price": float("nan"),
        "chg": float("nan"), "amount": float("nan"), "turn": 0.0,
        "tcap": 2e12, "fcap": 1.9e12,
    }]).to_parquet(tmp / "spot.parquet", index=False)
    (tmp / "float_shares.parquet").write_bytes(b"marker")

    raw = pd.DataFrame([{
        "代码": "600519", "名称": "新抓名称", "最新价": 1500.0, "涨跌幅": 1.0,
        "成交额": 1e9, "换手率": 0.5, "总市值": 2e12, "流通市值": 1.9e12,
    }])

    try:
        print("[1] 常规日更（底表存在、快照新鲜）")
        with patch.object(ak, "stock_zh_a_spot_em", return_value=raw) as m:
            df = fd.fetch_spot()
        check("未发起 clist 请求", m.call_count == 0)
        check("返回缓存快照", len(df) == 1 and df.iloc[0]["name"] == "缓存名称")

        print("[2] 显式 --refresh-spot 校准")
        with patch.object(ak, "stock_zh_a_spot_em", return_value=raw) as m:
            df = fd.fetch_spot(force=True)
        check("确实抓了一次", m.call_count == 1)
        check("新快照已落盘", (tmp / "spot.parquet").exists()
              and pd.read_parquet(tmp / "spot.parquet").iloc[0]["name"] == "新抓名称")

        print("[3] 无底表时仍走原路径（兼容降级）")
        (tmp / "float_shares.parquet").unlink()
        with patch.object(ak, "stock_zh_a_spot_em", return_value=raw) as m:
            fd.fetch_spot()
        check("回退到抓快照", m.call_count == 1)

        print("[4] 抓取失败但本地有缓存时不崩溃")
        (tmp / "float_shares.parquet").write_bytes(b"marker")
        with patch.object(ak, "stock_zh_a_spot_em",
                          side_effect=ConnectionError("RemoteDisconnected")):
            df = fd.fetch_spot(force=True)
        check("异常被兜底、返回缓存", len(df) == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：%d/%d 通过" % (sum(ok), len(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
