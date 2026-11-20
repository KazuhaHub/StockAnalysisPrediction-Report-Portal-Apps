"""Writes the three history files of testdata/pyarrow with the converter's own
writer (pipeline/mm_job.py), for as_of 2026-11-16: ``make_history.py <out-dir>``.

The Go tests install these files (history_store_test.go), so a change of the
history format has to regenerate them. CI also runs this inside the backend
image, as the restricted container user, and has the tests read the result.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in (os.path.join(HERE, "..", "..", "pipeline"), "/app/pipeline"):
    if os.path.exists(os.path.join(candidate, "mm_job.py")):
        sys.path.insert(0, candidate)
        break
import mm_job  # noqa: E402

DOCS = {
    "margin": [
        {"code": "600000", "name": "A", "price": 10.5, "frag": 90.0, "state": "临界", "level": "高", "tags": "a|b", "py": "A"},
        {"code": "000001", "name": "B", "price": None, "frag": 30.0, "state": "安全", "level": "低", "tags": ""},
        {"code": "300001", "name": "C", "price": 9.0, "frag": None, "state": "潜伏", "level": "低", "tags": "c"},
    ],
    "panorama": [
        {"code": "000001", "name": "平安银行", "sw1": "银行", "pe": 5.5, "label": "低估", "quad": "Q1", "profile": "P", "s_value": 60.0},
        {"code": "600000", "name": "浦发银行", "sw1": "银行", "pe": None, "label": "合理", "quad": "Q2", "profile": "P", "s_value": None},
    ],
    "etf": [
        {"code": "588000", "name": "科创50ETF", "cat": "科创50", "cum_ytd": 12.5, "cum20": 4.0},
        {"code": "510300", "name": "沪深300ETF", "cat": "宽基", "cum_ytd": None, "cum20": -1.5},
    ],
}

if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for module, rows in DOCS.items():
        mm_job.write_history(module, {"as_of": "2026-11-16", "rows": rows}, os.path.join(out, module + ".history.parquet"))
