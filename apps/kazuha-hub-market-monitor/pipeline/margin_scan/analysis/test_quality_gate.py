#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线验证 build_data 的两道质量闸门确实能拦住残缺数据。

不发网络、不碰任何数据文件：直接调用纯函数 quality_pre_gate / quality_post_gate。
用法：python3 analysis/test_quality_gate.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_data as bd  # noqa: E402

DATES = [(date(2026, 11, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
         for i in range(20)]
CODES = ["%06d" % i for i in range(10)]
results = []


def mk_bars(per_day=None):
    rows = []
    for d in DATES:
        codes = (per_day or {}).get(d, CODES)
        for c in codes:
            rows.append({"code": c, "date": d, "close": 10.0})
    return pd.DataFrame(rows)


def expect(label, fn, should_fail):
    try:
        fn()
        failed = False
        msg = "正常返回"
    except SystemExit as e:
        failed = True
        msg = str(e).split("\n")[0][:70]
    except Exception as e:
        print("  FAIL %s（异常类型错误 %s: %s）" % (label, type(e).__name__, e))
        results.append(False)
        return
    good = (failed == should_fail)
    print("  %s %-34s → %s" % ("PASS" if good else "FAIL", label, msg))
    results.append(good)


def main():
    print("[闸门 A] 行情基准日 / 覆盖率 / 日期连续性")
    normal = mk_bars()
    expect("正常数据应放行",
           lambda: bd.quality_pre_gate(normal, DATES[-1], DATES), False)
    expect("行情最新日≠两融基准日",
           lambda: bd.quality_pre_gate(normal, "2026-11-21", DATES), True)
    expect("基准日覆盖率腰斩(5/10)",
           lambda: bd.quality_pre_gate(mk_bars({DATES[-1]: CODES[:5]}),
                                       DATES[-1], DATES), True)
    expect("近20日仅有15天有行情",
           lambda: bd.quality_pre_gate(normal, DATES[-1],
                                       DATES + ["2026-11-%02d" % i for i in range(21, 26)]),
           True)

    print("[闸门 B] 池只数 / 融资余额 / 基准日")
    prev = {"overview": {"n_total": 3539, "rz_total": 21333.7},
            "meta": {"as_of": "2026-11-10"}}
    ov_ok = {"n_total": 3539, "rz_total": 21333.7}
    expect("正常数据应放行",
           lambda: bd.quality_post_gate(ov_ok, prev, "2026-11-11"), False)
    expect("股票池塌到2702(-24%)",
           lambda: bd.quality_post_gate({"n_total": 2702, "rz_total": 21333.7},
                                        prev, "2026-11-11"), True)
    expect("融资余额掉到15996亿(-25%)",
           lambda: bd.quality_post_gate({"n_total": 3539, "rz_total": 15996.0},
                                        prev, "2026-11-11"), True)
    expect("基准日倒退",
           lambda: bd.quality_post_gate(ov_ok, prev, "2026-11-09"), True)
    expect("首次运行无上一版则跳过",
           lambda: bd.quality_post_gate(ov_ok, None, "2026-11-11"), False)
    expect("同日手动重跑不误判",
           lambda: bd.quality_post_gate(ov_ok, prev, "2026-11-10"), False)

    print("\n结果：%d/%d 通过" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
