# -*- coding: utf-8 -*-
"""按缺口清单走 HTTP 接口批量补日线，边拉边落盘（可随时中断续跑）。

为什么不用 expand_run.py 的 pull 阶段
------------------------------------
expand_run 走 MCP `daily_hfq`，实测单票 284 秒；直连
`GET /api/v1/quotes/daily?adjust=hfq&...&return_format=csv` 同一份数据只要 7~30 秒。
口径完全一致（同一个 pytdx 源、同一个 batch_id、同一个 factor），
只是少了两层 MCP 封装与 JSON 序列化。

实测 2026-11-14 22:00 的吞吐：3 并发约 6~8 只/分钟（服务端同时在跑自己的
HKEX 回补任务，230 天没跑完，占着并发）。1,900 只 ≈ 5 小时，所以必须能断点续跑。

口径（与库内既有行对齐，2026-11-14 逐日核对 600519 / 001395）
--------------------------------------------------------------
  close  = hfq 后复权价，与 bars/*.parquet 完全一致
  factor = 复权因子，一致
  volume = `volume_raw`（真实股数）。库内 154 只新入库票实测就是 raw，
           不是 volume_adj；写错会让量能类因子整体偏差 factor 倍。
  amount = 真实成交额（元）

用法
----
  python3 bulk_pull.py                     # 跑完全部缺口（默认 3 并发）
  python3 bulk_pull.py --max-minutes 60    # 只跑一小时，剩下下次续
  python3 bulk_pull.py --workers 4 --limit 100
  python3 expand_run.py --stage ingest     # 拉完入库（前台）
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
import itertools
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402
import pandas as pd  # noqa: E402

GAP = os.path.join(HERE, "pool_gap_panorama.json")
CACHE = os.path.join(HERE, "pull_cache")
DONE = os.path.join(CACHE, "done.txt")
BASE = os.environ.get("QUOTE_API", "http://47.237.204.217:8000") + "/api/v1/quotes/daily"
START = "2014-06-01"
_lock = threading.Lock()

# 全局发送闸门。HTTP 通道同样会 429（2026-11-14 实测：连续拉 200 只后开始回 429），
# 而且是**整个账号**的总额度，所以必须像 market_data._pace_wait 那样统一控节奏：
# 多线程各自退避再同时重发，只会反复撞墙。
_PACE = {"next": 0.0, "gap": 5.0}
_PACE_MIN, _PACE_MAX = 5.0, 20.0
_PACE_LOCK = threading.Lock()


def _pace_wait() -> None:
    while True:
        with _PACE_LOCK:
            now = time.time()
            if now >= _PACE["next"]:
                _PACE["next"] = now + _PACE["gap"]
                return
            w = _PACE["next"] - now
        time.sleep(min(w, 0.5))


def _pace_slow_down() -> None:
    with _PACE_LOCK:
        _PACE["gap"] = min(_PACE_MAX, max(6.0, _PACE["gap"] * 1.8))
        _PACE["next"] = max(_PACE["next"], time.time() + _PACE["gap"])


def _pace_speed_up() -> None:
    with _PACE_LOCK:
        _PACE["gap"] = max(_PACE_MIN, _PACE["gap"] * 0.9)


def _asof() -> str:
    meta = json.load(open(os.path.join(HERE, "meta.json"), encoding="utf-8"))
    return meta["date_range"][1]


def _fetch(code: str, start: str, end: str, timeout: int = 300) -> pd.DataFrame:
    q = {"adjust": "hfq", "symbol": code, "start_date": start, "end_date": end,
         "return_format": "csv", "include_quality": "false"}
    url = BASE + "?" + urllib.parse.urlencode(q)
    raw = ""
    for attempt in range(3):
        _pace_wait()
        try:
            raw = urllib.request.urlopen(url, timeout=timeout).read().decode("utf-8")
            _pace_speed_up()
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                _pace_slow_down()
                time.sleep(_PACE["gap"])
                continue
            raise
    if not raw.strip():
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(raw))
    if df.empty:
        return df
    # 接口按时间倒序返回
    df = df.sort_values("time")
    out = pd.DataFrame({
        "code": code,
        "date": df["time"].astype(str).str[:10],
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df.get("volume_raw", df["volume"]), errors="coerce").fillna(0),
        "amount": pd.to_numeric(df["amount"], errors="coerce").fillna(0),
        "factor": pd.to_numeric(df["factor"], errors="coerce").fillna(1),
        "tradestatus": pd.to_numeric(df.get("tradestatus", 1), errors="coerce").fillna(1).astype(int),
    })
    out = out[out["close"] > 0]
    return out[list(md.ORDER)]


def _targets() -> list[str]:
    g = json.load(open(GAP, encoding="utf-8"))
    codes = [x["code"] for ch in g["batches"].values() for x in ch]
    have = set(md.codes())
    done = set()
    if os.path.exists(DONE):
        done = {ln.strip() for ln in open(DONE, encoding="utf-8") if ln.strip()}
    return [c for c in codes if md.norm_code(c) not in have and md.norm_code(c) not in done]


def _next_idx() -> int:
    fs = glob.glob(os.path.join(CACHE, "pull_*.parquet"))
    return (max(int(os.path.basename(p)[5:9]) for p in fs) + 1) if fs else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--shard", type=int, default=40, help="每多少只写一个 parquet")
    ap.add_argument("--max-minutes", type=float, default=0, help="0=跑完为止")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", default=START)
    a = ap.parse_args()

    os.makedirs(CACHE, exist_ok=True)
    todo = _targets()
    if a.limit:
        todo = todo[:a.limit]
    if not todo:
        print("没有待补的票，跑 expand_run.py --stage ingest 入库")
        return 0
    end = _asof()
    print(f"待补 {len(todo)} 只 ｜ {a.start} ~ {end} ｜ {a.workers} 并发", flush=True)

    t0 = time.time()
    idx = _next_idx()
    buf, ok, fail, n_done = [], 0, [], 0
    # 只保持「并发数×2」个在飞任务，不要一次 submit 全部。
    # 2026-11-14 踩过：把 2,060 个 future 全塞进 ThreadPoolExecutor 后，
    # `--max-minutes` 里的 break 只是跳出消费循环，`with` 退出时 executor 会
    # 等**队列里所有**任务跑完——进程挂着继续拉、shard 不再落盘，进度全丢。
    # 有界窗口下，break 最多丢 2×workers 只在飞请求。
    ex = ThreadPoolExecutor(max_workers=a.workers)
    it = iter(todo)
    inflight: dict = {}
    for c in itertools.islice(it, a.workers * 2):
        inflight[ex.submit(_fetch, c, a.start, end)] = c

    while inflight:
        done_set, _ = wait(inflight, return_when=FIRST_COMPLETED)
        for fu in done_set:
            c = inflight.pop(fu)
            n_done += 1
            try:
                df = fu.result()
                if df.empty:
                    fail.append(c)
                else:
                    buf.append(df)
                    ok += 1
                    with _lock, open(DONE, "a", encoding="utf-8") as f:
                        f.write(c + "\n")
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                fail.append(c)
                print(f"  ! {c} {repr(e)[:80]}", flush=True)

            nxt = next(it, None)
            if nxt is not None:
                inflight[ex.submit(_fetch, nxt, a.start, end)] = nxt

            if len(buf) >= a.shard or n_done == len(todo):
                if buf:
                    out = os.path.join(CACHE, f"pull_{idx:04d}.parquet")
                    pd.concat(buf, ignore_index=True).to_parquet(out + ".tmp", index=False,
                                                                 compression="zstd")
                    os.replace(out + ".tmp", out)
                    print(f"  → {os.path.basename(out)}  {len(buf)} 只", flush=True)
                    idx += 1
                    buf = []
            if n_done % 20 == 0:
                el = time.time() - t0
                print(f"  [{n_done}/{len(todo)}] ok {ok} fail {len(fail)}  "
                      f"{el/60:.1f} 分  {n_done/el*60:.1f} 只/分", flush=True)
                # 日更（.update.lock）一旦起来就收尾：两边打同一台上游，同时全速只会
                # 互相 429。已拉到的分片已经落盘，驱动脚本下一轮会暂停，不会丢数据。
                if os.path.isdir(os.path.join(HERE, ".update.lock")):
                    print("  检测到行情库日更启动，本批提前收尾（已拉的已落盘）", flush=True)
                    for fu in inflight:
                        fu.cancel()
                    break
        if a.max_minutes and (time.time() - t0) / 60 >= a.max_minutes:
            print("  到时退出，剩余下次续跑", flush=True)
            # 剩下的在飞请求不再等待：丢掉结果比挂在这里干等强（下一轮会重拉）
            for fu in inflight:
                fu.cancel()
            break
    # 收尾：把已经攒在内存里的 shard 落盘，别因为超时丢了
    if buf:
        out = os.path.join(CACHE, f"pull_{idx:04d}.parquet")
        pd.concat(buf, ignore_index=True).to_parquet(out + ".tmp", index=False, compression="zstd")
        os.replace(out + ".tmp", out)
        print(f"  → {os.path.basename(out)}  {len(buf)} 只（收尾）", flush=True)

    ex.shutdown(wait=False, cancel_futures=True)

    if fail:
        with open(os.path.join(HERE, "pending_bulk.txt"), "a", encoding="utf-8") as f:
            for c in fail:
                f.write(c + "\n")
    print(f"\n完成 {ok}/{len(todo)} 只，{(time.time()-t0)/60:.1f} 分钟，失败 {len(fail)} 只",
          flush=True)
    print("入库：python3 expand_run.py --stage ingest", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
