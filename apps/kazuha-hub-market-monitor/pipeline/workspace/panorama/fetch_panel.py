"""抓取 12 期 PIT 财务面板（2023-12-31 ~ 2026-09-30 各报告期横截面），
用于历史 PE/PB 带、ROE 稳定性、增长加速度等因子。"""
import json
import time

import mcpc
from asof import asof_compact

PERIODS = ["20231231", "20240331", "20240630", "20240930", "20241231", "20250331",
           "20250630", "20250930", "20251231", "20260331", "20260630", "20260930"]

FIELDS = ",".join([
    "instrument_id", "symbol", "report_period", "available_at",
    "revenue", "net_income", "operating_cf", "total_assets", "total_liabilities",
    "equity", "shares_outstanding", "eps", "bps", "ocfps", "roe", "roa",
    "gross_margin", "net_margin", "operating_margin", "asset_liability_ratio",
    "rev_yoy", "np_yoy", "ttm_net_income", "ttm_revenue", "inventory", "receivables",
])


def main():
    m = mcpc.MCP(mcpc.SERVER_URL).init()
    all_rows = []
    for rp in PERIODS:
        rows, off, total = [], 0, None
        for _ in range(6):
            r = m.call("query_financial_pit", {"action": "cross_section", "as_of": asof_compact(),
                                               "report_period": rp, "fields": FIELDS,
                                               "limit": 2000, "offset": off})
            items = r.get("items") or []
            total = r.get("total")
            rows += items
            off += 2000
            if not items or off >= (total or 0):
                break
            time.sleep(0.2)
        print(f"{rp}: {len(rows)}/{total}", flush=True)
        all_rows += rows
        time.sleep(0.3)
    json.dump(all_rows, open("data/panel.json", "w"), ensure_ascii=False)
    print("rows", len(all_rows))


if __name__ == "__main__":
    main()
