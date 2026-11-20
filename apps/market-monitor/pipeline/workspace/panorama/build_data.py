"""Panorama 数据层：从本地 stock-server MCP 抓全市场 PIT 基本面 / 行业 / 行情快照。

产物（parquet/json，放在 data/）：
  fundamentals_latest.json   最新可知报告期横截面
  fundamentals_hist.json     FY2023/FY2024/FY2025 年报横截面（做 3 年 CAGR、ROE 稳定性）
  industry.json              申万一级时点分类
  quotes.json                最新行情快照（价格、市值）
"""
import json
import os
import sys
import time

import mcpc
from asof import asof_compact

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT, exist_ok=True)

FIELDS = ",".join([
    "instrument_id", "symbol", "exchange", "report_period", "available_at",
    "revenue", "net_income", "ttm_revenue", "ttm_net_income", "operating_cf",
    "total_cf", "total_assets", "total_liabilities", "equity",
    "current_assets", "current_liabilities", "inventory", "receivables",
    "fixed_assets", "intangible_assets", "shares_outstanding",
    "current_ratio", "quick_ratio", "eps", "bps", "ocfps", "roe", "roa",
    "gross_margin", "net_margin", "operating_margin", "asset_liability_ratio",
    "rev_yoy", "np_yoy", "operating_profit", "fiscal_year", "fiscal_quarter",
    "is_delisted", "available_at_quality", "share_validation",
])


def paged(m, tool, base, key="items", page=2000, maxpage=10, sleep=0.3):
    rows, off = [], 0
    for _ in range(maxpage):
        a = dict(base)
        a.update({"limit": page, "offset": off})
        r = m.call(tool, a)
        items = r.get(key) or []
        rows.extend(items)
        total = r.get("total") or 0
        off += page
        if off >= total or not items:
            break
        time.sleep(sleep)
    return rows, total


def main():
    m = mcpc.MCP("http://localhost:8091/mcp").init()
    ASOF = asof_compact()

    # 1) 最新 PIT 横截面
    rows, total = paged(m, "query_financial_pit",
                        {"action": "cross_section", "as_of": ASOF, "fields": FIELDS})
    print(f"latest cross_section: {len(rows)}/{total}")
    json.dump(rows, open(f"{OUT}/fundamentals_latest.json", "w"), ensure_ascii=False)

    # 2) 历史年报横截面（3 年 CAGR / ROE 稳定性）
    hist = {}
    for rp in ["20231231", "20241231", "20251231"]:
        rows, total = paged(m, "query_financial_pit",
                            {"action": "cross_section", "as_of": ASOF, "report_period": rp,
                             "fields": FIELDS})
        hist[rp] = rows
        print(f"  FY {rp}: {len(rows)}")
    json.dump(hist, open(f"{OUT}/fundamentals_hist.json", "w"), ensure_ascii=False)

    # 3) 申万一级时点分类
    rows, total = paged(m, "query_industry_data",
                        {"action": "as_of", "as_of_date": ASOF, "as_of_taxonomy_system": "sw"})
    print(f"industry: {len(rows)}/{total}")
    json.dump(rows, open(f"{OUT}/industry.json", "w"), ensure_ascii=False)

    print("done")


if __name__ == "__main__":
    main()
