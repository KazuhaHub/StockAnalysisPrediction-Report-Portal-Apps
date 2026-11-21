"""
带超时的MCP工具全面测试

每个工具调用最多等待15秒，避免单个接口卡住影响全部测试。
"""

import sys
import time
import threading
sys.path.insert(0, r"c:\MarsPlan\stock_server")

import stock_mcp_integrated as m


def run_with_timeout(func, args, kwargs, timeout=15):
    """带超时执行函数，返回 (结果, 是否超时)"""
    result = [None]
    error = [None]

    def worker():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        return None, True  # 超时
    if error[0] is not None:
        raise error[0]
    return result[0], False


def test_one(name, func, kwargs, timeout=20, logfile=None):
    """测试单个工具"""
    try:
        s = time.time()
        r, timed_out = run_with_timeout(func, [], kwargs, timeout)
        e = time.time() - s

        if timed_out:
            line = f"[TMO] {name:<42} | 超时(>{timeout}s)"
        elif isinstance(r, dict) and "error" in r:
            msg = str(r["error"])[:65]
            line = f"[ERR] {name:<42} | {e:.1f}s | {msg}"
        elif isinstance(r, dict):
            line = f"[OK ] {name:<42} | {e:.1f}s | keys={list(r.keys())[:5]}"
        elif isinstance(r, list):
            line = f"[OK ] {name:<42} | {e:.1f}s | list[{len(r)}]"
        else:
            line = f"[OK ] {name:<42} | {e:.1f}s | {str(r)[:60]}"
    except Exception as ex:
        line = f"[EXC] {name:<42} | {type(ex).__name__}: {str(ex)[:60]}"
        timed_out = False

    print(line, flush=True)
    if logfile:
        logfile.write(line + "\n")
        logfile.flush()
    return "TIMEOUT" if timed_out else ("ERROR" if "ERR" in line else "OK")


# 全部测试用例
tests = [
    ("get_daily_stock_data", m.get_daily_stock_data,
     {"stock_code": "600519", "start_date": "2026-06-01", "end_date": "2026-06-14"}),
    ("get_latest_stock_data", m.get_latest_stock_data,
     {"stock_codes": ["600519"]}),
    ("get_trading_calendar_data", m.get_trading_calendar_data,
     {"exchange": "SSE", "start_date": "2026-06-01", "end_date": "2026-06-14"}),
    ("get_next_trading_day", m.get_next_trading_day,
     {"exchange": "SSE", "date": "2026-05-30"}),
    ("get_previous_trading_day", m.get_previous_trading_day,
     {"exchange": "SSE", "date": "2026-05-30"}),
    ("get_instruments", m.get_instruments,
     {"exchange": "SSE", "limit": 5}),
    ("get_stock_info", m.get_stock_info,
     {"stock_code": "600519"}),
    ("get_instrument_by_id", m.get_instrument_by_id,
     {"instrument_id": "600519.SH"}),
    ("get_company_industry", m.get_company_industry,
     {"instrument_id": "600519.SH"}),
    ("get_financial_statements", m.get_financial_statements,
     {"instrument_id": "600519.SH"}),
    ("get_shareholders", m.get_shareholders,
     {"instrument_id": "600519.SH"}),
    ("get_relative_valuation", m.get_relative_valuation,
     {"instrument_id": "600519.SH"}),
    ("get_dcf_valuation", m.get_dcf_valuation,
     {"instrument_id": "600519.SH"}),
    ("get_server_technical_summary", m.get_server_technical_summary,
     {"instrument_id": "600519.SH"}),
    ("get_server_technical_indicators", m.get_server_technical_indicators,
     {"instrument_id": "600519.SH", "limit": 3}),
    ("get_industry_taxonomy", m.get_industry_taxonomy, {}),
    ("get_industry_component_sets", m.get_industry_component_sets,
     {"sw_index_code": "801010"}),
    ("get_industry_index_analysis", m.get_industry_index_analysis,
     {"sw_index_code": "801010"}),
    ("get_technical_analysis", m.get_technical_analysis,
     {"stock_code": "600519", "start_date": "2026-04-01", "end_date": "2026-06-14"}),
    ("get_ma_analysis", m.get_ma_analysis,
     {"stock_code": "600519", "start_date": "2026-04-01", "end_date": "2026-06-14"}),
    ("get_macd_analysis", m.get_macd_analysis,
     {"stock_code": "600519", "start_date": "2026-04-01", "end_date": "2026-06-14"}),
    ("get_kdj_analysis", m.get_kdj_analysis,
     {"stock_code": "600519", "start_date": "2026-04-01", "end_date": "2026-06-14"}),
    ("get_regression_beta", m.get_regression_beta,
     {"stock_code": "600519", "start_date": "2026-01-01", "end_date": "2026-06-14"}),
    # 卡住风险高的接口放最后
    ("get_financial_statements_history", m.get_financial_statements_history,
     {"instrument_id": "600519.SH"}),
]


def main():
    logfile = open(r"c:\MarsPlan\stock_server\test_result.txt", "w", encoding="utf-8")
    header = f"MCP工具全面测试（带超时20s）  共{len(tests)}个工具"
    print("=" * 105, flush=True)
    print(header, flush=True)
    print("=" * 105, flush=True)
    logfile.write("=" * 105 + "\n" + header + "\n" + "=" * 105 + "\n")
    logfile.flush()

    stats = {"OK": 0, "ERROR": 0, "TIMEOUT": 0, "EXCEPTION": 0}
    for name, func, params in tests:
        result = test_one(name, func, params, logfile=logfile)
        if result in stats:
            stats[result] += 1

    summary = (f"总计: {len(tests)}个  |  成功: {stats['OK']}  |  "
               f"错误: {stats['ERROR']}  |  超时: {stats['TIMEOUT']}  |  异常: {stats['EXCEPTION']}")
    print("=" * 105, flush=True)
    print(summary, flush=True)
    logfile.write("=" * 105 + "\n" + summary + "\n")
    logfile.close()


if __name__ == "__main__":
    main()
