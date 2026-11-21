# -*- coding: utf-8 -*-
"""按 pool_gap.json 的批次把缺口票补进本地行情库。**两阶段**跑。

为什么拆成两个阶段
------------------
`ingest` 要原子替换 `bars/*.parquet`，这类操作在受管环境里需要逐次审批（前台可以
自动放行，后台任务拿不到审批，会以 `PermissionError: Brokered host rename source
refused by file policy` 失败——而且报在 ingest，看着像数据源问题，实际一只都没入库）。

所以拆开：
  **pull**   只拉数据写成 `pull_cache/pull_*.parquet`（新建文件，后台无阻碍），
             这个阶段长、慢、受上游限流支配，适合后台跑。
  **ingest** 读缓存一次性写库（13 个分区各替换一次），短、快，前台跑一次审批即可。

用法
----
  # 阶段 1（可后台，几十分钟）
  python3 expand_run.py --stage pull --batch AC --workers 10 --chunk 100
  # 阶段 2（必须前台，十分钟内）
  python3 expand_run.py --stage ingest
  # 只重试上次失败的票
  python3 expand_run.py --stage pull --retry-pending
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market_data as md  # noqa: E402

GAP = os.path.join(HERE, "pool_gap.json")
CACHE = os.path.join(HERE, "pull_cache")
PENDING = os.path.join(HERE, "pending_add.txt")
PROGRESS = os.path.join(HERE, "expand_progress.json")
KEYS = {"A": "A_现存缺口_上市早于2015", "B": "B_现存缺口_2015后上市",
        "C": "C_退市_库区间内有历史", "D": "D_退市_库起点前已退",
        "E": "E_全市场缺口_沪深"}

_tls = threading.local()


def _cli(timeout: int):
    """每线程一个会话：MCP 的 self._id / self.sid 不是线程安全的。
    握手 < 0.1s，真正的开销在上游查询，按线程复用足够。"""
    import market_data as md
    s = getattr(_tls, "cli", None)
    if s is None:
        s = md.StockServer(timeout=timeout)
        _tls.cli = s
    return s


def _fetch(code: str, start: str, end: str, timeout: int) -> dict:
    """走 md._fetch_range，而不是自己 new 一个会话直连。

    2026-11-08 那轮就是这样失败的：`_cli(timeout).daily_hfq()` 绕过了
    market_data 的**全局发送闸门**（`_pace_wait`），10 个线程各自全速发，
    上游按总量限流，于是 40%~60% 的票被 429 打回，而且慢下来的是"倒霉的那只"，
    不是整个批次。改成 _fetch_range 后，429 触发的是全局减速，所有线程一起等。
    retries=2：真限流有两次机会，真没数据也不会把整批拖住。
    """
    return md._fetch_range(code, start, end, retries=2)


def _stamp() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _targets(a) -> list[str]:
    if a.retry_pending:
        if not os.path.exists(PENDING):
            print("没有 pending_add.txt")
            return []
        codes = [ln.split("#")[0].strip() for ln in open(PENDING, encoding="utf-8")]
        codes = [c for c in codes if c]
    else:
        g = json.load(open(a.gap or GAP, encoding="utf-8"))
        codes = []
        for ch in a.batch.upper():
            codes += [x["code"] for x in g["batches"][KEYS[ch]]]
    have = set(md.codes())
    return [c for c in codes if md.norm_code(c) not in have]


# ---------------------------------------------------------------- 阶段 1
def stage_pull(a) -> int:
    import pandas as pd
    import market_data as md

    todo = _targets(a)
    print(f"批次 {a.batch}：待补 {len(todo)} 只", flush=True)
    if a.dry_run or not todo:
        return 0
    os.makedirs(CACHE, exist_ok=True)
    md._ping()
    start = a.start or md.DEFAULT_START
    end = md._today()

    prog = {"stage": "pull", "started": _stamp(), "batch": a.batch,
            "n_todo": len(todo), "chunks": [], "fail": [], "done_total": 0}
    # 编号必须接续已有缓存。用 0 起算的话，二轮重试会直接覆盖掉第一轮拉好的
    # pull_0000.parquet——而且不报错，等 ingest 时才发现少了 100 只票。
    _existing = glob.glob(os.path.join(CACHE, "pull_*.parquet"))
    base_idx = 0
    if _existing:
        base_idx = max(int(os.path.basename(p)[5:9]) for p in _existing) + 1
        print(f"  已有 {len(_existing)} 个缓存文件，本轮从 pull_{base_idx:04d} 起编号")
    names = {}
    np_ = os.path.join(CACHE, "names.json")
    if os.path.exists(np_):
        names = json.load(open(np_, encoding="utf-8"))
    t0 = dt.datetime.now()
    ok_all = 0

    for i in range(0, len(todo), a.chunk):
        part = todo[i:i + a.chunk]
        t1 = dt.datetime.now()
        rows, fail, done = [], [], 0
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(_fetch, md.norm_code(c), start, end, a.timeout): c for c in part}
            for fu in as_completed(futs):
                c = md.norm_code(futs[fu])
                done += 1
                try:
                    r = fu.result()
                    bars = r.get("bars") or []
                    if not bars:
                        fail.append({"code": c, "err": "返回 0 根 bar"})
                    else:
                        names[c] = r.get("name") or names.get(c) or c
                        for b in bars:
                            rows.append((c, str(b["d"])[:10],
                                         float(b.get("o", None) or 0), float(b.get("h", None) or 0),
                                         float(b.get("l", None) or 0), float(b.get("c", None) or 0),
                                         float(b.get("v", 0) or 0), float(b.get("amt", 0) or 0),
                                         float(b.get("f", 0) or 0), int(b.get("trd", 1) or 1)))
                except Exception as e:                        # noqa: BLE001
                    fail.append({"code": c, "err": repr(e)[:110]})
                if done % 20 == 0:
                    prog["done_total"] = ok_all + done - len(fail)
                    prog["last"] = _stamp()
                    _write_json(PROGRESS, prog)

        n_ok = len(part) - len(fail)
        if rows:
            df = pd.DataFrame(rows, columns=md.ORDER)
            out = os.path.join(CACHE, f"pull_{base_idx + i // a.chunk:04d}.parquet")
            df.to_parquet(out + ".tmp", index=False, compression="zstd")
            os.replace(out + ".tmp", out)
        ok_all += n_ok
        sec = (dt.datetime.now() - t1).total_seconds()
        rate = len(part) / sec * 60 if sec else 0
        eta = (len(todo) - i - len(part)) / rate if rate else 0
        prog["chunks"].append({"at": _stamp(), "n": len(part), "ok": n_ok,
                               "fail": len(fail), "sec": round(sec, 1)})
        prog["fail"] += fail
        prog["done_total"] = ok_all
        prog["last"] = _stamp()
        _write_json(PROGRESS, prog)
        _write_json(np_, names)
        print(f"  [{i // a.chunk + 1:>3}] {i + len(part):>5}/{len(todo)}  "
              f"ok {n_ok:>3} fail {len(fail):>3}  {sec:.0f}s  "
              f"{rate:.1f} 只/分  ETA {eta:.0f} 分", flush=True)
        if fail:
            with open(PENDING, "a", encoding="utf-8") as f:
                for x in fail:
                    f.write(f"{x['code']}  # {x['err']}\n")

    total = (dt.datetime.now() - t0).total_seconds()
    prog.update(finished=_stamp(), n_ok=ok_all, sec=round(total, 1))
    _write_json(PROGRESS, prog)
    print(f"\n拉取完成：{ok_all}/{len(todo)} 只，{total/60:.1f} 分钟 → {CACHE}")
    if prog["fail"]:
        print(f"失败 {len(prog['fail'])} 只，已记 {PENDING}；跑 --retry-pending 二轮")
    print("下一步（必须在能获得写盘审批的前台终端跑）："
          "python3 expand_run.py --stage ingest")
    return 0


# ---------------------------------------------------------------- 阶段 2
def stage_ingest(a) -> int:
    import pandas as pd
    import market_data as md

    files = sorted(glob.glob(os.path.join(CACHE, "pull_*.parquet")))
    if not files:
        print(f"{CACHE} 里没有 pull_*.parquet，先跑 --stage pull")
        return 2
    print(f"读到 {len(files)} 个缓存文件，合并中…", flush=True)
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df = df[df["close"] > 0]
    codes = sorted(df["code"].unique())
    print(f"  {len(df):,} 行 / {len(codes)} 只 ｜ {df['date'].min()} ~ {df['date'].max()}",
          flush=True)
    if a.dry_run:
        return 0

    added, years = md._new_partitions(df)
    meta = md._read_meta()
    st = meta.setdefault("stocks", {})
    names = json.load(open(os.path.join(CACHE, "names.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(CACHE, "names.json")) else {}
    # 退市标记必须落到 meta 上，不能只体现在"这只票的 bars 到某年就断了"。
    # 下游 qdata 靠它算 includes_delisted，doctor 靠它判断"幸存者偏差修没修"。
    # 不写这一步的后果：数据补齐了，能力表仍报 含退市 False，等于白补。
    #
    # list_date 也在这里一起填：fill_meta.py 的数据源是**现存**名单的
    # stock_info_*_name_code，退市股不在里面，等它补等于永远补不到；
    # 而退市股缺 list_date 会被 filter_listing_age 判成"无法证明当时已上市"整只剔掉。
    extra_meta: dict[str, dict] = {}
    if os.path.exists(GAP):
        g = json.load(open(a.gap or GAP, encoding="utf-8"))
        for key, st_tag in (("C_退市_库区间内有历史", "delisted"),
                            ("A_现存缺口_上市早于2015", "alive")):
            for x in g["batches"].get(key) or []:
                extra_meta[x["code"]] = {"status": st_tag,
                                         "list_date": x.get("list_date"),
                                         "delist_date": x.get("delist_date")}
    stats = md._stats_of(codes, years)
    now = _stamp()
    n_new = 0
    for code in codes:
        if code not in st:
            n_new += 1
        old = st.get(code) or {}
        s = stats.get(code) or {}
        ex = extra_meta.get(code) or {}
        rec = {"name": names.get(code) or old.get("name") or code,
               "board": old.get("board"),
               "list_date": old.get("list_date") or ex.get("list_date"),
               "sw1": old.get("sw1"), "sw2": old.get("sw2"),
               "sw3": old.get("sw3"), "sw_l3_code": old.get("sw_l3_code"),
               "first": s.get("first") or old.get("first"),
               "last": s.get("last") or old.get("last"),
               "n_bars": int(s.get("n") or 0), "updated": now}
        if ex.get("status") == "delisted" or old.get("status") == "delisted":
            rec["status"] = "delisted"
            rec["delist_date"] = ex.get("delist_date") or old.get("delist_date")
        elif old.get("status"):
            rec["status"] = old["status"]
        st[code] = rec
    n_del = sum(1 for v in st.values() if v.get("status") == "delisted")
    n_nold = sum(1 for v in st.values() if not v.get("list_date"))
    meta["date_range"] = md._date_range(meta)
    meta["n_bars"] = md._n_bars()
    md._write_meta(meta)
    print(f"入库完成：新增 {n_new} 只 / 合计 {len(codes)} 只 ｜ "
          f"新增 {sum(added.values()):,} 行 ｜ 分区 {','.join(sorted(added))}")
    print(f"         全库 {len(st)} 只，其中退市 {n_del} 只、缺 list_date {n_nold} 只")
    if n_nold:
        print(f"         ⚠ 还有 {n_nold} 只没有 list_date：会被上市年限过滤整只剔掉。"
              f"跑 fill_meta.py 补（它对退市股无效，退市日靠 pool_gap.json）")
    print("下一步：fill_meta.py 补 sw1，然后 test --all 重算")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["pull", "ingest"], default="pull")
    ap.add_argument("--batch", default="AC")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--chunk", type=int, default=100)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--start", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry-pending", action="store_true")
    ap.add_argument("--gap", default=None, help="缺口清单路径，默认 pool_gap.json")
    a = ap.parse_args()
    return stage_pull(a) if a.stage == "pull" else stage_ingest(a)


if __name__ == "__main__":
    sys.exit(main())
