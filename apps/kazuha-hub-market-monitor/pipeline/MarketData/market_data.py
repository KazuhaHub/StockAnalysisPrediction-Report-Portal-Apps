# -*- coding: utf-8 -*-
"""本地 A 股行情库（后复权日线）：读 → 增量更新 → 加票 → 校验，全部离线可用。

为什么要有这个库
----------------
研究脚本每次现抓数据有三个问题：慢（单只 20–30 秒）、不可复现（源会变、会截断）、
浪费（同一份历史被重复下载几十遍）。本库把"取一次、永久存、以后只补增量"做成默认路径。

目录结构
--------
    ~/MarketData/
        market_data.py      本文件（自包含，可整体拷走）
        bars/YYYY.parquet   按年分区的长表（code, date, o/h/l/c, volume, amount, factor, tradestatus）
        meta.json           每只票的元信息（名称/板块/行业/首末日期/条数）+ 全局统计
        updates.jsonl       每次增量更新的审计日志（新增行数、失败票、异常告警）

快速上手
--------
    import sys; sys.path.insert(0, "~/MarketData")   # 或把该目录加进 PYTHONPATH
    import market_data as md

    md.load(codes=["600519", "000001"], start="2020-01-01")   # 长表 DataFrame
    md.panel("close", start="2024-01-01")                     # 宽表：日期 × 代码
    md.status()                                               # 数据到哪天了

命令行
------
    python3 ~/MarketData/market_data.py status
    python3 ~/MarketData/market_data.py update            # 增量：只补上次之后的新 bar
    python3 ~/MarketData/market_data.py update --codes 600519 000001
    python3 ~/MarketData/market_data.py add 688981        # 加票（自动补全历史）
    python3 ~/MarketData/market_data.py verify            # 完整性校验
    python3 ~/MarketData/market_data.py export --start 2020-01-01 --out panel.csv

复权口径
--------
存**后复权**（hfq）。`close` 是后复权价，`factor` 是累计复权因子，
真实成交价 = close / factor。选后复权的原因是它**不随未来除权重算历史**：
新增 bar 直接 append 即可，不需要回改旧数据——这是"增量更新"能成立的前提。
前复权则会在每次除权后整体重算，做增量必然对不齐。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = os.path.abspath(os.environ.get("MARKET_DATA_HOME")
                       or os.path.join(os.path.expanduser("~"), "MarketData"))
BARS = os.path.join(ROOT, "bars")
META = os.path.join(ROOT, "meta.json")
LOG = os.path.join(ROOT, "updates.jsonl")
SNAP = os.path.join(ROOT, "snapshots")
SNAP_KEEP = 3           # 保留最近几次写入前的副本
# 为什么从 10 降到 3：快照的粒度是"一次写事务"，而补票是按单票循环调 add 的——
# 一只票一份全库快照。10 份听起来不多，实际是 10 × 全库旧版本 ≈ 3 GB，而
# 第 10 份的回滚价值几乎为零（增量写只增行，退回去等于把后面 9 次合法新增扔了）。
# 真正的回滚需求是"刚写的这一批坏了"，退一步就够，所以 3 份是够用且便宜的量。

ORDER = ["code", "date", "open", "high", "low", "close",
         "volume", "amount", "factor", "tradestatus"]
SCHEMA = pa.schema([("code", pa.string()), ("date", pa.string()),
                    ("open", pa.float64()), ("high", pa.float64()),
                    ("low", pa.float64()), ("close", pa.float64()),
                    ("volume", pa.float64()), ("amount", pa.float64()),
                    ("factor", pa.float64()), ("tradestatus", pa.int8())])

SS_URL = os.environ.get("STOCK_SERVER_URL", "http://localhost:8091/mcp")
DEFAULT_START = "2014-06-01"      # 比常用面板起点早一年，留出计算窗口的缓冲
PENDING_UPDATE = os.path.join(ROOT, "pending_update.txt")   # 本次没补上的票，次日优先
_lock = threading.Lock()

# 请求节流（见「增量更新」一节的说明）。基准 0.2 秒 ≈ 5 个请求/秒，
# 1500 只票约 5 分钟；撞 429 就把间隔翻倍，最高 2 秒。
_PACE = {"gap": 0.2, "next": 0.0, "hits": 0}
_PACE_LOCK = threading.Lock()
_PACE_BASE = 0.2
_PACE_MAX = 2.0
_THROTTLE_RETRIES = 6


# ---------------------------------------------------------------- 小工具
def _today() -> str:
    return dt.date.today().isoformat()


def norm_code(x: str) -> str:
    """`600519.SH` / `sh600519` / `600519` → `600519`。"""
    s = str(x).strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    s = s.removeprefix("SH").removeprefix("SZ").removeprefix("BJ")
    return s.zfill(6) if s.isdigit() else s


def _ensure():
    os.makedirs(BARS, exist_ok=True)


def _read_meta() -> dict:
    if not os.path.exists(META):
        return {"version": 1, "stocks": {}}
    with open(META, encoding="utf-8") as f:
        return json.load(f)


def _write_meta(m: dict) -> None:
    """原子写：先写 tmp 再 replace，避免中断留下半个 meta.json。"""
    m["n_codes"] = len(m.get("stocks") or {})
    m["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    tmp = META + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    os.replace(tmp, META)


def _log(rec: dict) -> None:
    rec.setdefault("ts", dt.datetime.now().isoformat(timespec="seconds"))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 读
def codes() -> list[str]:
    return sorted((_read_meta().get("stocks") or {}).keys())


def universe() -> pd.DataFrame:
    """每只票一行的元信息表（索引为代码）。"""
    st = _read_meta().get("stocks") or {}
    if not st:
        return pd.DataFrame(columns=["name", "board", "list_date", "sw1", "first", "last", "n_bars"])
    df = pd.DataFrame.from_dict(st, orient="index")
    df.index.name = "code"
    return df


def _dataset() -> ds.Dataset:
    files = sorted(glob.glob(os.path.join(BARS, "*.parquet")))
    if not files:
        raise FileNotFoundError(f"{BARS} 下没有 parquet 分区，先跑一次 `market_data.py import`")
    return ds.dataset(BARS, format="parquet")


def load(codes=None, start=None, end=None, columns=None, as_datetime=True) -> pd.DataFrame:
    """读长表。`codes/start/end` 都会下推成 parquet 过滤，不把全库读进内存。"""
    expr = None
    if start:
        expr = ds.field("date") >= str(start)
    if end:
        e = ds.field("date") <= str(end)
        expr = e if expr is None else (expr & e)
    if codes:
        e = ds.field("code").isin([norm_code(c) for c in codes])
        expr = e if expr is None else (expr & e)
    cols = list(columns) if columns else ORDER
    df = _dataset().to_table(columns=cols, filter=expr).to_pandas()
    if as_datetime and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    if len(df):
        df = df.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    return df


def panel(field: str = "close", codes=None, start=None, end=None, dtype=None) -> pd.DataFrame:
    """宽表：index=日期, columns=代码, values=`field`。做截面因子最顺手。

    直接从 arrow 表按字典编码的下标填 numpy 数组，不经过「长表 → pivot」：
    全库 5,000+ 只 × 12 年的长表在 pandas 里是两列 Python 字符串，单列就要
    1–2 GB，2 GiB 内存的容器里会被 OOM 直接杀掉（没有任何报错输出）。
    `dtype` 默认沿用该列的类型；传 "float32" 再省一半。同一 (date, code) 有
    重复行时保留最后一行。"""
    import pyarrow.compute as _pc
    expr = None
    if start:
        expr = ds.field("date") >= str(start)
    if end:
        e = ds.field("date") <= str(end)
        expr = e if expr is None else (expr & e)
    if codes:
        e = ds.field("code").isin([norm_code(c) for c in codes])
        expr = e if expr is None else (expr & e)
    files = sorted(glob.glob(os.path.join(BARS, "*.parquet")))
    if not files:
        raise FileNotFoundError(f"{BARS} 下没有 parquet 分区，先跑一次 `market_data.py import`")
    # 逐个年度分区读：每次只有一个分区的字符串列在内存里，留下的只是两列
    # int32 下标和数值列。
    parts, out_dtype = [], np.dtype(dtype) if dtype else None
    for path in files:
        t = ds.dataset(path, format="parquet").to_table(columns=["code", "date", field], filter=expr)
        if t.num_rows == 0:
            continue
        cd = _pc.dictionary_encode(t.column("code")).combine_chunks()
        dd = _pc.dictionary_encode(t.column("date")).combine_chunks()
        vals = t.column(field).to_numpy()
        if out_dtype is None:
            out_dtype = vals.dtype if vals.dtype.kind == "f" else np.dtype(np.float64)
        parts.append((np.asarray(cd.dictionary.to_pylist(), dtype=object),
                      np.asarray([str(x)[:10] for x in dd.dictionary.to_pylist()], dtype=object),
                      cd.indices.to_numpy(zero_copy_only=False).astype(np.int32),
                      dd.indices.to_numpy(zero_copy_only=False).astype(np.int32),
                      vals.astype(out_dtype, copy=False)))
        del t, cd, dd, vals
    if not parts:
        return pd.DataFrame()
    code_v = np.unique(np.concatenate([p[0] for p in parts]))
    date_v = np.unique(np.concatenate([p[1] for p in parts]))
    arr = np.full((len(date_v), len(code_v)), np.nan, dtype=out_dtype)
    for cv, dv, ci, di, vals in parts:   # 后面的分区覆盖前面的：重复行保留最后一行
        arr[np.searchsorted(date_v, dv)[di], np.searchsorted(code_v, cv)[ci]] = vals
    del parts
    return pd.DataFrame(arr, index=pd.DatetimeIndex(pd.to_datetime(date_v), name="date"),
                        columns=pd.Index(code_v, name="code"))


def bars_of(code: str, start=None, end=None) -> pd.DataFrame:
    return load(codes=[code], start=start, end=end)


# ---------------------------------------------------------------- 写
def _new_partitions(df_new: pd.DataFrame, tag: str = "", protect: bool = True,
                    snap: bool = True) -> tuple[dict, list]:
    """把新 bar 按年分组，逐分区与旧数据合并去重后原子写回。返回 (每年新增行数, 冲突年份)。

    **这是唯一的分区写入口**（`ingest`、扩池脚本、修复脚本都走它），所以三道防线
    全部收在这里，而不是挂在某一个调用方身上：
      ① 写前给将要改动的分区拍硬链接快照 + 记指纹
      ② 逐分区拒绝"合并后变少"（丢行或丢票都中止）
      ③ 写后比对指纹，再核一遍
    把防线放在调用方（比如只放在 `ingest`）的后果：扩池脚本直接调本函数、
    绕开 `ingest`，最大的那次写入恰好没有快照。

    `snap=False` 只省掉①的快照、指纹比对照做：`update` 一晚分批写十来次，只在第一批
    前拍一次，否则 SNAP_KEEP 份轮换会把"今晚开写之前"那份挤掉，回滚点就没了。
    """
    df_new = df_new.copy()
    df_new["date"] = df_new["date"].astype(str)
    df_new["_y"] = df_new["date"].str.slice(0, 4)
    years_want = sorted(df_new["_y"].unique())
    before = partition_stats(years_want) if protect else {}
    if protect and snap:
        snapshot(years_want, tag=tag or "write", quiet=True, stats=before)
    added, touched = {}, []
    for y, chunk in df_new.groupby("_y"):
        chunk = chunk.drop(columns=["_y"])
        p = os.path.join(BARS, f"{y}.parquet")
        if os.path.exists(p):
            old = pd.read_parquet(p)
            old_keys = old.drop_duplicates(["code", "date"])
            n_old_rows = len(old_keys)      # 注意别写成 before：外层那个是快照指纹
            n_old_codes = int(old["code"].nunique())
            merged = pd.concat([old, chunk], ignore_index=True)
            merged = merged.drop_duplicates(["code", "date"], keep="last")
            # 写之前必须证明"只增不减"。写入是 os.replace 原子替换，
            # 一旦这里丢了旧行，磁盘上就再也没有第二份——而且不报错。
            # 真实事故：2014 分区被增量数据整块顶掉，968 只票的
            # 2014-06-03~2014-12-31 共 138,975 根 bar 静默消失，
            # 直到 verify() 报「meta 对不上的票 1201」才被发现。
            if len(merged) < n_old_rows:
                raise RuntimeError(
                    f"{y}.parquet 写入会丢 {n_old_rows - len(merged):,} 行"
                    f"（旧 {n_old_rows:,} → 新 {len(merged):,}），已中止。"
                    f"若确实要缩减分区，显式调用 rebuild_partition()。")
            n_new_codes = int(merged["code"].nunique())
            if n_new_codes < n_old_codes:
                raise RuntimeError(
                    f"{y}.parquet 写入会丢 {n_old_codes - n_new_codes} 只票"
                    f"（旧 {n_old_codes} → 新 {n_new_codes}），已中止。")
            added[y] = len(merged) - n_old_rows
        else:
            # 分区文件"应该存在却不存在"= 上一步已经把它弄丢了。这时走新建分支
            # 会把本批数据当成整年数据写回去，旧行永久消失且不报错——2014 那次
            # 事故就是这一支。判据用 meta 的 date_range：库起点到末期之间的
            # 每一年都必须有分区；只有"往更早的年份扩历史"才允许新建。
            rng = (_read_meta().get("date_range") or [None, None])
            y0 = str(rng[0])[:4] if rng[0] else None
            y1 = str(rng[1])[:4] if rng[1] else None
            if y0 and y1 and y0 <= y <= y1:
                raise RuntimeError(
                    f"{y}.parquet 不见了（库区间 {y0}~{y1} 内的分区必须存在）。"
                    f"已中止，别用新建分支把整年数据覆盖掉。"
                    f"先查是谁删的；确认要重建就显式调用 rebuild_partition()。")
            merged = chunk.drop_duplicates(["code", "date"], keep="last")
            added[y] = len(merged)
        merged = merged.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
        for c in ("tradestatus",):
            merged[c] = merged[c].fillna(1).astype("int8")
        tbl = pa.Table.from_pandas(merged[ORDER], schema=SCHEMA, preserve_index=False)
        tmp = p + ".tmp"
        pq.write_table(tbl, tmp, compression="zstd", row_group_size=200_000)
        os.replace(tmp, p)
        touched.append(y)
    if protect:
        after = partition_stats(touched)
        drift = _diff_stats(before, after)
        if drift:
            # 逐分区守卫已经拒绝了"变少"，走到这里意味着有路径绕过了它。
            # 数据已经落盘，能做的只有：留证、把回滚命令交到手上、让调用方失败。
            detail = "; ".join(f"{d['year']} 行 {d['rows'][0]}→{d['rows'][1]}、"
                               f"票 {d['codes'][0]}→{d['codes'][1]}" for d in drift)
            _log({"kind": "integrity_alert", "tag": tag, "drift": drift})
            raise RuntimeError(f"写入后分区变小：{detail}。回滚：market_data.py snapshots")
    return added, touched


def rebuild_partition(year: str, df: pd.DataFrame, quiet: bool = False,
                      protect: bool = True) -> int:
    """整分区替换（会删掉该分区里 df 没有的行）。只给修复脚本用，不走增量路径。

    存在的理由：增量写入被 `_new_partitions` 禁止缩减，所以"我确实要重写这一年的
    数据"必须有单独入口，而不是把守卫关掉。调用方负责先把完整数据准备好。

    这一条路径**最容易毁数据**（它按定义就会删行），所以照样先拍快照。
    实测代价可以忽略，而 2026-11-08 那次演练正是靠这份快照把砍掉的 33 万行拿回来的。
    """
    if df.empty:
        raise ValueError("rebuild_partition 收到空表，拒绝把分区清空")
    if protect and os.path.exists(os.path.join(BARS, f"{year}.parquet")):
        snapshot([year], tag="rebuild", quiet=True, stats=partition_stats([year]))
    p = os.path.join(BARS, f"{year}.parquet")
    out = df.copy()
    out["date"] = out["date"].astype(str)
    out = out.drop_duplicates(["code", "date"], keep="last")
    out = out.sort_values(["code", "date"], kind="mergesort").reset_index(drop=True)
    for c in ("tradestatus",):
        out[c] = out[c].fillna(1).astype("int8")
    tbl = pa.Table.from_pandas(out[ORDER], schema=SCHEMA, preserve_index=False)
    tmp = p + ".tmp"
    pq.write_table(tbl, tmp, compression="zstd", row_group_size=200_000)
    os.replace(tmp, p)
    if not quiet:
        print(f"  {year}.parquet 已整分区重写：{len(out):,} 行 / "
              f"{out['code'].nunique():,} 只")
    return len(out)


# ---------------------------------------------------------------- 写入保护
# 为什么需要这一层：`bars/*.parquet` 的写入是 `os.replace` 原子替换——好处是
# 中断不会留下半个文件，代价是**旧数据没有第二份**。2026-11-08 就发生过一次：
# 2014 分区被一批增量当成整年数据写回去，968 只票 / 138,975 根 bar 直接消失，
# 而当时所有检查都在问"池子里有什么"，没有一项在问"旧数据还在不在"。
#
# 三道防线，从便宜到贵：
#   1. `partition_stats()`  写入前后各取一次指纹（行数/票数/日期区间/异年行）
#   2. 硬链接快照          写入前把将要改动的分区钉住，回滚成本 O(1)、空间 O(0)
#   3. `_new_partitions() ` 的只增不减守卫  直接拒绝写
# 前两道是"发现并可以退回去"，第三道是"不让它发生"。三道都要有：
# 守卫只能看到单个分区，快照能救回守卫拦不住的情况（比如整分区被 rebuild 覆盖）。

def partition_stats(years=None) -> dict:
    """每分区的指纹：行数 / 票数 / 日期区间 / 落在别年的行数。

    全部走 pyarrow 的列式算子，不把数据读进 Python 对象：全库 13 个分区约 1 秒。
    行数用 parquet footer（毫秒级），票数用 `count_distinct`，日期区间用 `min_max`。
    `stray` 是"这个分区里不属于这一年的行"——2026-11-08 就在 2014 分区里捞到过
    一根 000001 2026-11-06 的假 bar，它和 2026 分区撞成 (code,date) 重复，
    还会在那只票的序列尾造出 −99.8% 的假收益。分区纯度是能零成本查的。
    """
    want = {str(y) for y in years} if years else None
    out: dict[str, dict] = {}
    for p in sorted(glob.glob(os.path.join(BARS, "*.parquet"))):
        y = os.path.basename(p)[:4]
        if want is not None and y not in want:
            continue
        rows = int(pq.ParquetFile(p).metadata.num_rows)
        t = pq.read_table(p, columns=["code", "date"])
        mm = pc.min_max(t.column("date")).as_py() if rows else {"min": None, "max": None}
        matched = int(pc.sum(pc.cast(pc.starts_with(t.column("date"), y),
                                     pa.int64())).as_py() or 0) if rows else 0
        out[y] = {"rows": rows,
                  "codes": int(pc.count_distinct(t.column("code")).as_py()) if rows else 0,
                  "min": mm.get("min"), "max": mm.get("max"),
                  "stray": rows - matched}
    return out


def snapshot(years=None, tag: str = "", keep: int | None = None,
             quiet: bool = True, stats: dict | None = None) -> dict:
    """把指定分区**硬链接**一份到 `snapshots/<时间戳>/`，返回 {stamp, years, ...}。

    为什么用硬链接而不是复制：`_new_partitions` 是"写 .tmp 再 os.replace"，
    替换只改目录项，**旧 inode 的内容完好**，所以硬链接指向的仍是旧数据。
    成本是几次 `os.link`（微秒级）、空间是 0；只有真被替换掉之后，旧 inode
    才由快照独占——一次日常 update 只改当年那一个分区，约 30 MB。
    跨设备（快照目录被挪到别的卷）时 `os.link` 会失败，退化成复制。

    只快照**已经存在**的分区：新建分区没有旧数据可保护。

    `MD_SNAPSHOT_COPY=1` 时改成复制（在平台里跑时由 mm_job 设）：硬链接是同一文件的
    第二个链接，平台更新前的数据检查点拒收 nlink>1 的文件。

    `years=None` 才是"全部已存在分区"；显式传空列表是"没有分区要保护"，必须
    什么都不拍。这两者以前被 `if years` 混成一支——空列表走成 falsy，于是
    一次空写入会给全库拍 13 个分区的快照。2026-11-10 那 87 份快照里，78 份
    就是这么来的（内容与当前 bars 完全同一 inode，回滚等于原地不动）。
    """
    if years is not None and not list(years):
        return {"stamp": None, "years": [], "linked": 0, "copied": 0}
    want = [str(y) for y in years] if years is not None else \
        [os.path.basename(p)[:4] for p in glob.glob(os.path.join(BARS, "*.parquet"))]
    todo = [y for y in want if os.path.exists(os.path.join(BARS, f"{y}.parquet"))]
    if not todo:
        return {"stamp": None, "years": [], "linked": 0, "copied": 0}
    # 时间戳带毫秒：只用秒会在同一秒内撞名，而"撞名就加后缀"有个更坏的副作用——
    # 旧的那份被清理掉之后，原来的名字又能被复用，快照目录就不再是单调递增的，
    # 排序即时间的假设随之失效（清理会删错）。毫秒 + 零填充计数器，两头都堵住。
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    if tag:
        stamp += "-" + "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:24]
    d = os.path.join(SNAP, stamp)
    n = 1
    while os.path.exists(d):
        n += 1
        d = os.path.join(SNAP, f"{stamp}#{n:02d}")
    os.makedirs(d, exist_ok=True)
    linked = copied = 0
    copy_only = os.environ.get("MD_SNAPSHOT_COPY") == "1"
    for y in todo:
        src = os.path.join(BARS, f"{y}.parquet")
        dst = os.path.join(d, f"{y}.parquet")
        try:
            if copy_only:
                raise OSError("copy requested")
            os.link(src, dst)
            linked += 1
        except OSError:
            import shutil
            shutil.copy2(src, dst)
            copied += 1
    rec = {"stamp": os.path.basename(d), "years": todo,
           "linked": linked, "copied": copied, "at": dt.datetime.now().isoformat(timespec="seconds")}
    # 把写前指纹一起记下来：事后要问"这次写入前后到底动了多少"，不用去翻文件
    if stats:
        rec["parts"] = {y: [s["rows"], s["codes"]] for y, s in stats.items() if y in todo}
    _log({"kind": "snapshot", **rec})
    gone, freed = _prune_snapshots(keep if keep is not None else SNAP_KEEP, quiet=quiet)
    if gone:
        rec["pruned"], rec["freed_mb"] = gone, round(freed, 1)
    if not quiet:
        print(f"  快照 {rec['stamp']}：{len(todo)} 个分区"
              f"（硬链接 {linked}{'、复制 ' + str(copied) if copied else ''}）")
        if gone:
            print(f"  清理旧快照 {len(gone)} 份，释放 {freed / 1e6:.0f} MB")
    return rec


def list_snapshots() -> list[dict]:
    """按时间倒序列出快照：名字里带时间戳，目录名排序即时间序。

    `own_mb` 是这份快照**独占**的空间（硬链接数为 1 的文件）——只有那些分区
    后来被真正替换掉、旧 inode 无人共享时才会出现。`mb` 是名义大小，硬链接下
    这个数字只是"看起来占了多少"，别拿它评估成本。
    """
    out = []
    for d in sorted(glob.glob(os.path.join(SNAP, "*")), reverse=True):
        if not os.path.isdir(d):
            continue
        files = sorted(glob.glob(os.path.join(d, "*.parquet")))
        own = [f for f in files if os.stat(f).st_nlink == 1]
        out.append({"stamp": os.path.basename(d),
                    "years": [os.path.basename(f)[:4] for f in files],
                    "mb": round(sum(os.path.getsize(f) for f in files) / 1e6, 1),
                    "own_mb": round(sum(os.path.getsize(f) for f in own) / 1e6, 1)})
    return out


def _prune_snapshots(keep: int, quiet: bool = True) -> tuple[list[str], float]:
    """只保留最近 keep 次。删的是我们自己生成的目录，且只删 snapshots/ 下一层。

    这里踩过一个坑：原来写的是 `shutil.rmtree(d, ignore_errors=True)`，然后不管
    删没删成都往 `gone` 里塞。在受限环境（后台任务 / 沙箱）里 unlink 被拒时，
    异常被吞掉，函数照样报告"清理了 N 份"——2026-11-10 复盘发现 87 份快照、
    2.4 GB 独占空间，正是这样积起来的，日志里一次报错都没有。
    所以：**删完必须复查目录是否真的消失**，没消失就抛错，让调用方失败。
    """
    import shutil
    snaps = list_snapshots()
    gone, freed, stuck = [], 0.0, []
    for s in snaps[keep:]:
        d = os.path.join(SNAP, s["stamp"])
        if os.path.dirname(os.path.abspath(d)) != os.path.abspath(SNAP):
            continue                      # 绝不越界删
        freed += s["own_mb"] * 1e6        # 只算能真正释放的部分
        try:
            shutil.rmtree(d)
        except OSError as e:
            stuck.append(f"{s['stamp']}（{type(e).__name__}: {str(e)[:60]}）")
            continue
        if os.path.exists(d):
            stuck.append(f"{s['stamp']}（目录仍在）")
            continue
        gone.append(s["stamp"])
    if stuck:
        raise RuntimeError(
            f"快照清理失败，{len(stuck)} 份没删掉：" + "；".join(stuck[:3])
            + "。快照只增不减会把磁盘吃满，先修权限再继续写入。")
    if gone and not quiet:
        print(f"  清理旧快照 {len(gone)} 份（保留最近 {keep} 份），释放 {freed / 1e6:.0f} MB")
    return gone, freed


def _snapshot_space() -> dict:
    """快照目录的真实成本：独占字节数（名义大小在有硬链接时是虚的）。"""
    files = glob.glob(os.path.join(SNAP, "*", "*.parquet"))
    own = [f for f in files if os.stat(f).st_nlink == 1]
    return {"files": len(files), "own_files": len(own),
            "own_mb": round(sum(os.path.getsize(f) for f in own) / 1e6, 1),
            "dirs": len([d for d in glob.glob(os.path.join(SNAP, "*")) if os.path.isdir(d)])}


def restore(stamp: str, years=None, quiet: bool = False) -> dict:
    """从快照恢复分区。恢复前会先把当前状态另存一份，避免"恢复到一半又丢了"。"""
    d = os.path.join(SNAP, stamp)
    if not os.path.isdir(d):
        raise SystemExit(f"没有这个快照：{stamp}\n现有："
                         + ", ".join(s["stamp"] for s in list_snapshots()[:5]))
    files = sorted(glob.glob(os.path.join(d, "*.parquet")))
    want = {str(y) for y in years} if years else None
    files = [f for f in files if want is None or os.path.basename(f)[:4] in want]
    if not files:
        raise SystemExit(f"快照 {stamp} 里没有要恢复的分区")
    snapshot([os.path.basename(f)[:4] for f in files], tag="before-restore", quiet=quiet)
    import shutil
    for f in files:
        y = os.path.basename(f)[:4]
        dst = os.path.join(BARS, f"{y}.parquet")
        tmp = dst + ".tmp"
        shutil.copy2(f, tmp)
        os.replace(tmp, dst)               # 走同一条原子路径，不是 shutil.copy 直接盖
    rebuild_meta(quiet=True)
    rec = {"kind": "restore", "from": stamp, "years": [os.path.basename(f)[:4] for f in files]}
    _log(rec)
    if not quiet:
        print(f"已从 {stamp} 恢复 {len(files)} 个分区："
              f"{', '.join(rec['years'])}；meta 已按磁盘重算")
    return rec


def _diff_stats(before: dict, after: dict) -> list[dict]:
    """两次指纹之间的缩减。只报"变少"——变多是正常的增量。"""
    drift = []
    for y in sorted(set(before) & set(after)):
        b, a = before[y], after[y]
        if a["rows"] < b["rows"] or a["codes"] < b["codes"]:
            drift.append({"year": y,
                          "rows": [b["rows"], a["rows"]],
                          "codes": [b["codes"], a["codes"]]})
    return drift


def _stats_of(codes, years) -> dict:
    """从**已落盘**的分区回算 first/last/n_bars。

    为什么不直接用"旧数 + 新增条数"：增量批里可能包含与旧数据重叠的日期
    （源端重发当天 bar），相加会重复计数。以磁盘为准才是唯一可信的口径。
    """
    want = set(codes)
    out = {}
    for y in sorted(set(years)):
        p = os.path.join(BARS, f"{y}.parquet")
        if not os.path.exists(p):
            continue
        t = pd.read_parquet(p, columns=["code", "date"])
        t = t[t["code"].isin(want)]
        for c, g in t.groupby("code", sort=False):
            e = out.setdefault(c, {"first": "9999", "last": "", "n": 0})
            e["first"] = min(e["first"], str(g["date"].min()))
            e["last"] = max(e["last"], str(g["date"].max()))
            e["n"] += len(g)
    return out


def ingest(records, source: str = "manual", quiet: bool = False,
           protect: bool = True, snap: bool = True) -> dict:
    """通用写入：records 是 [{code,name,bars:[{d,o,h,l,c,v,amt,trd,f}], ...}, ...]。

    迁移旧缓存、导入外部 CSV 都走这里，保证磁盘格式只有一种。
    元信息只做"并集"（名称/行业缺省时保留旧值），日期与条数以落盘结果回算。

    `protect=True`（默认）会在写入前给**将要改动的分区**留硬链接快照，并在写后
    比对指纹，发现"分区变小"就报警并抛出。批量迁移（`import_ss_cache`）关掉它：
    源文件本身还在，且一次迁移会触碰全部 13 个分区、连做几十批，快照纯属浪费。
    """
    _ensure()
    rows, info = [], {}
    for rec in records:
        code = norm_code(rec.get("code") or "")
        bars = rec.get("bars") or []
        if not code or not bars:
            continue
        for b in bars:
            rows.append((code, str(b["d"])[:10],
                         float(b.get("o", np.nan)), float(b.get("h", np.nan)),
                         float(b.get("l", np.nan)), float(b.get("c", np.nan)),
                         float(b.get("v", 0.0) or 0.0), float(b.get("amt", 0.0) or 0.0),
                         float(b.get("f", 0.0) or 0.0), int(b.get("trd", 1) or 1)))
        info.setdefault(code, rec)
    if not rows:
        return {"n_codes": 0, "n_bars": 0, "new": 0, "years": {}}
    df = pd.DataFrame(rows, columns=ORDER)
    # 四价必须齐全且为正。缺价的 bar 不是"便宜的数据"，是毒数据：
    # 一根 close=1、OHLC 全 NaN 的行进了分区，会在该票序列里造出一个 −99% 的
    # 单日收益，并且因为 verify 只查重复/OHLC 关系，它一路绿灯。
    px = df[["open", "high", "low", "close"]]
    good = np.isfinite(px).all(axis=1) & (df["close"] > 0)
    if not bool(good.all()):
        n_bad = int((~good).sum())
        df = df[good].reset_index(drop=True)
        if not quiet:
            print(f"丢弃 {n_bad} 根价格缺失/非正的 bar（四价必须齐全且 close>0）")
    if df.empty:
        return {"n_codes": 0, "n_bars": 0, "new": 0, "years": {}}

    # 快照 / 指纹 / 只增不减守卫都在 `_new_partitions` 里——它是唯一的分区写入口，
    # 扩池与修复脚本也走那里。放在这里只保护 `ingest` 一条路，等于白做。
    added, years = _new_partitions(df, tag=source, protect=protect, snap=snap)

    meta = _read_meta()
    st = meta.setdefault("stocks", {})
    # 2026-11-11 修复：以前只把**本次触碰**的年份传给 `_stats_of`（增量永远只碰当年），
    # 于是 first 被写成当年 1 月、n_bars 写成本年根数——每跑一次成功增量就把整批票的
    # 历史统计抹掉，事后只能靠 `rebuild-meta` 善后（11-03/04/05/06/09 各复发一次）。
    # 改成扫全部分区年：`_stats_of` 内部先按 want 过滤，只读这批票的 code/date 两列，
    # 13 个分区合计仍是个位秒级，放在一次 ingest 的尾部完全可接受。
    all_years = sorted({f[:4] for f in os.listdir(BARS) if f.endswith(".parquet")})
    stats = _stats_of(list(info), all_years)
    now = dt.datetime.now().isoformat(timespec="seconds")
    for code, rec in info.items():
        old = st.get(code) or {}
        s = stats.get(code) or {}
        st[code] = {"name": rec.get("name") or old.get("name") or code,
                    "board": rec.get("board") or old.get("board"),
                    "list_date": rec.get("list_date") or old.get("list_date"),
                    "sw1": rec.get("sw1") or old.get("sw1"),
                    "sw2": rec.get("sw2") or old.get("sw2"),
                    "sw3": rec.get("sw3") or old.get("sw3"),
                    "sw_l3_code": rec.get("sw_l3_code") or old.get("sw_l3_code"),
                    "first": s.get("first") or old.get("first"),
                    "last": s.get("last") or old.get("last"),
                    "n_bars": int(s.get("n") or rec.get("n_bars") or 0),
                    "updated": now}
    meta["source"] = meta.get("source") or source
    meta["adjust"] = "hfq"
    meta["date_range"] = _date_range(meta)
    _write_meta(meta)
    tot = int(sum(added.values()))
    if not quiet:
        print(f"写入 {len(rows):,} 行 → 新增 {tot:,} 行，分区 {','.join(sorted(years))}")
    return {"n_codes": len(info), "n_bars": len(rows), "new": tot, "years": added}


# ---------------------------------------------------------------- stock-server 客户端
class StockServer:
    """stock-server MCP 的最小 HTTP 客户端（本机 http://localhost:8091/mcp）。

    不走 agent 侧 MCP 调用，是因为一天 1500 只票的数据过一遍上下文没有意义：
    数据要直接落盘，不过对话。协议：initialize 拿 Mcp-Session-Id，响应是 SSE 帧。
    """

    def __init__(self, url: str = SS_URL, timeout: int = 240) -> None:
        self.url, self.timeout, self.sid, self._id = url, timeout, None, 0
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "market-data", "version": "1.0"}})
        try:
            self._rpc("notifications/initialized", {}, notify=True)
        except Exception:                                   # noqa: BLE001
            pass

    def _rpc(self, method: str, params: dict, notify: bool = False):
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            self._id += 1
            payload["id"] = self._id
        hdr = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
        if self.sid:
            hdr["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=hdr)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            sid = r.headers.get("Mcp-Session-Id")
            if sid:
                self.sid = sid
            txt = r.read().decode("utf-8")
        for line in txt.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(txt) if txt.strip() else None

    def call(self, name: str, args: dict, retries: int = 3):
        last = None
        for a in range(retries):
            try:
                res = self._rpc("tools/call", {"name": name, "arguments": args})
                sc = (res or {}).get("result", {})
                if sc.get("isError"):
                    raise RuntimeError(str(sc)[:300])
                txt = "".join(c.get("text", "") for c in sc.get("content") or [])
                return json.loads(txt)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = e
                time.sleep(1.5 * (a + 1))
        raise RuntimeError(f"{name} 连续失败：{last!r}")

    def daily_hfq(self, code: str, start: str, end: str, retries: int = 3) -> dict:
        d = self.call("query_stock_quote", {"action": "daily", "stock_code": code,
                                            "start_date": start, "end_date": end,
                                            "adjust": "hfq"}, retries=retries)
        # 数据源失败时返回的是 {"error": "..."}，没有 data 字段。
        # 若当成"没有新 bar"处理，增量更新会把一次服务故障记成"已是最新"——
        # 这是数据型项目最危险的静默失败，必须炸出来。
        if d.get("error"):
            raise RuntimeError(f"数据源报错：{str(d['error'])[:160]}")
        bars = []
        for r in d.get("data") or []:
            try:
                bars.append({"d": str(r["time"])[:10],
                             "o": float(r["open"]), "h": float(r["high"]),
                             "l": float(r["low"]), "c": float(r["close"]),
                             "v": float(r.get("volume") or 0.0),
                             "amt": float(r.get("amount") or 0.0),
                             "trd": int(r.get("tradestatus") or 1),
                             "f": float(r.get("factor") or 0.0)})
            except (KeyError, TypeError, ValueError):
                continue
        bars.sort(key=lambda x: x["d"])
        return {"code": d.get("instrument_id") or code, "name": d.get("name") or code,
                "bars": bars}


def _ping() -> None:
    """先握手一次：连不上就立刻给出可读的错误，而不是让 N 个线程各自超时。"""
    try:
        StockServer(timeout=20)
    except Exception as e:                                   # noqa: BLE001
        raise SystemExit(f"连不上 stock-server（{SS_URL}）：{type(e).__name__}。\n"
                         "本库读取不需要它；只有 update / add 需要。"
                         "先把 stock-server 起起来再试。") from None


# ---------------------------------------------------------------- 增量更新
#
# 429 是服务端**整体**限流，不是某只票的数据有问题。原来的处理链条是：
# 单票重试 3 次全失败 → 抛错 → update 记一次 fail → 连续 18 次判定"源端故障"
# → 收工。实测后果：2026-11-02~11-05 连续四晚都在 0005xx 这一段被 429 截断，
# 每晚只跑 47/1524 只，退出码却是 0，238 只票的 last 一路停在 10-30。
#
# 所以限流必须在**发送节奏**上解决：一个全局闸门控住所有线程的请求速率，
# 撞到 429 就一起放慢（而不是各自退避后同时重发，那样必然再撞一次），
# 而且限流不算"源端故障"，不能作为熔断依据。
def _pace_wait() -> None:
    """领一个发送许可：全局 `gap` 秒内只放一个请求过去。"""
    while True:
        with _PACE_LOCK:
            now = time.time()
            if now >= _PACE["next"]:
                _PACE["next"] = now + _PACE["gap"]
                return
            wait = _PACE["next"] - now
        time.sleep(min(wait, 0.5))


def _pace_slow_down() -> None:
    with _PACE_LOCK:
        _PACE["hits"] += 1
        _PACE["gap"] = min(_PACE_MAX, max(_PACE_BASE * 2, _PACE["gap"] * 2))
        _PACE["next"] = max(_PACE["next"], time.time() + _PACE["gap"])


def _pace_speed_up() -> None:
    """成功一次就往回收一点，避免限流过去之后还在慢跑。

    收敛要快：从 2 秒回落到基准只要十来次成功。原来每步只乘 0.97，
    要七十多次才回来——一场短暂限流会让整晚都慢跑。
    """
    with _PACE_LOCK:
        if _PACE["gap"] > 0:
            _PACE["gap"] *= 0.9
            if _PACE["gap"] < _PACE_BASE:
                _PACE["gap"] = _PACE_BASE


def _is_throttle(err) -> bool:
    s = str(err)
    return "429" in s or "too many requests" in s.lower()


_CLIENT = threading.local()


def _client() -> StockServer:
    """每个线程复用一个 MCP 会话。

    原来每只票都新建 StockServer——一次 initialize 加一次 tools/call，
    1500 只票就是 3000 次请求，其中一半纯属浪费，也因此更容易撞限流。
    """
    s = getattr(_CLIENT, "s", None)
    if s is None:
        s = StockServer()
        _CLIENT.s = s
    return s


def _drop_client() -> None:
    """会话可能被服务端回收了（重启、超时），下次重建。"""
    _CLIENT.s = None


def _fetch_range(code: str, start: str, end: str, retries: int = _THROTTLE_RETRIES) -> dict:
    last = None
    for _ in range(retries):
        _pace_wait()
        try:
            # 内层重试交给外层统一控节奏：两套退避叠在一起会变成不可预测的等待。
            r = _client().daily_hfq(code, start=start, end=end, retries=1)
            _pace_speed_up()
            return r
        except Exception as e:                               # noqa: BLE001
            low = str(e).lower()
            if any(k in low for k in ("session", "http error 400", "http error 404")):
                _drop_client()                               # 会话失效，不是数据问题
            if not _is_throttle(e):
                raise
            last = e
            _pace_slow_down()
    raise RuntimeError(f"{code} 连续 {retries} 次被限流（最后：{str(last)[:80]}）")


# 北交所：920xxx（2024 年换号后）、8xxxxx / 4xxxxx（换号前）。MCP 通道认不出它们的交易所，
# 一律报「无法识别股票代码 … 的交易所」（README §4.1：只有 HTTP 通道能取北交所）。
_BSE_PREFIXES = ("920", "8", "4")

# 探针优先用这几只：流动性最好、几乎不会停牌，取不到就只能是源端的问题。
_PROBE_ANCHORS = ("600519", "000001", "601318", "600036", "000333", "600000")


def _is_bse(code: str) -> bool:
    return str(code).startswith(_BSE_PREFIXES)


def _channel_unsupported(code: str, err) -> bool:
    """通道不支持这只票（不是源端故障）：只认北交所代码的「无法识别交易所」。

    主板票报同样的错是真故障，照常计入失败和熔断。
    """
    s = str(err)
    return _is_bse(code) and "无法识别" in s and "交易所" in s


def _pick_probe(plan: list) -> int | None:
    """探针在 plan 里的下标：通道取得到的流动性好的票，永远不选北交所。

    2026-11-23 生产事故：上轮没补上的北交所代码排在最前，探针取 plan[0]
    → MCP 报「无法识别交易所」→ 整轮 5,589 只被当成"数据源不可用"中止。
    全是北交所时返回 None：没有能代表整源状态的票，交给逐只处理。
    """
    idx = {c: i for i, (c, _, _) in enumerate(plan)}
    for a in _PROBE_ANCHORS:
        if a in idx:
            return idx[a]
    for i, (c, _, _) in enumerate(plan):
        if c.startswith(("60", "00")):                       # 沪深主板
            return i
    for i, (c, _, _) in enumerate(plan):
        if not _is_bse(c) and not c.startswith(("200", "900")):   # B 股通道也未必支持
            return i
    return None


def _collect(code: str, r: dict, st: dict, got: dict, warn: list) -> int:
    """把一次抓取结果并进待写批次，并检查新旧衔接是否异常。有新 bar 返回 1，否则 0。"""
    bars = [b for b in r.get("bars") or [] if b["d"] > (st.get(code) or {}).get("last", "")]
    if not bars:
        return 0
    got[code] = {"code": code, "name": r.get("name") or (st.get(code) or {}).get("name"),
                 "bars": bars}
    # 复权基准若被源改过，新旧衔接处会出现超出涨跌停的跳空
    prev = (st.get(code) or {}).get("last_close")
    if prev and bars[0].get("c") and abs(bars[0]["c"] / prev - 1) > 0.25:
        warn.append({"code": code, "last_close": prev, "new_close": bars[0]["c"]})
    return 1


def _read_pending() -> list[str]:
    """上一轮没补上的票。格式 `code\t已到哪一天`，`#` 起注释。"""
    if not os.path.exists(PENDING_UPDATE):
        return []
    out = []
    try:
        with open(PENDING_UPDATE, encoding="utf-8") as f:
            for ln in f:
                ln = ln.split("#")[0].strip()
                if ln:
                    out.append(ln.split()[0])
    except OSError:
        return []
    return out


def _write_pending(lag: dict) -> None:
    """把还没补上的票写回清单。

    没有这份清单时，每天 `sorted(st)` 都从 000001 开始，同一段票每晚再撞一次
    限流，后面的永远轮不到——238 只票停在 10-30 就是这么来的。
    """
    tmp = PENDING_UPDATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"# 增量更新没补上的票（{dt.date.today()} 自动写，格式：code  已到哪一天）\n")
        for c, last in sorted(lag.items()):
            f.write(f"{c}\t{last}\n")
    os.replace(tmp, PENDING_UPDATE)


# 边取边写的批量。2026-11-26 补跑在 4000/4392 只时撞上 4 小时上限被杀，攒到最后才写的
# 结果是一根都没进库；现在每攒够这么多只就写一次，被杀最多丢最后一批，下一轮从断点续上。
# 每批要重写当年分区（十几秒）；快照只在当晚第一批前拍一次（见 `_new_partitions` 的 snap）。
FLUSH_EVERY = 1000


def _flush(got: dict, quiet: bool, snap: bool = True) -> int:
    """把攒下的这批写进库，并记下每只票的最后收盘价（下次跳空检查用）。返回新增行数。"""
    if not got:
        return 0
    res = ingest(got.values(), source="stock-server/update", quiet=quiet, snap=snap)
    m2 = _read_meta()
    # 一次读回这批票的最后收盘价（不要一只一只读）
    d = load(codes=list(got), columns=["code", "date", "close"], as_datetime=False)
    if len(d):
        last = d.sort_values("date").groupby("code")["close"].last()
        for c, v in last.items():
            m2["stocks"].setdefault(c, {})["last_close"] = float(v)
    m2["date_range"] = _date_range(m2)
    m2["n_bars"] = _n_bars()
    _write_meta(m2)
    got.clear()
    return res["new"]


def update(codes=None, workers: int = 6, end: str | None = None,
           dry_run: bool = False, quiet: bool = False, limit: int | None = None,
           flush_every: int = FLUSH_EVERY) -> dict:
    """增量：每只票从 `meta.last` 的次日补到 `end`（默认今天）。不重下历史。"""
    meta = _read_meta()
    st = meta.get("stocks") or {}
    if not st:
        raise SystemExit("库是空的，先 `market_data.py add CODE...` 或 `import` 旧缓存")
    end = end or _today()
    pend = set(_read_pending())
    if codes:
        targets = [norm_code(c) for c in codes]
    else:
        targets = [c for c in sorted(st) if c in pend]
        targets += [c for c in sorted(st) if c not in pend]
    # 退市股不再增量：它们的 last 就是终止上市日，往后每天都会白跑一次请求，
    # 而且返回必然为空，容易被误读成"数据源挂了"。要重拉用 add。
    targets = [c for c in targets
               if c in st and (st[c].get("status") or "alive") != "delisted"]
    plan, skip = [], []
    for c in targets:
        last = st[c].get("last") or DEFAULT_START
        start = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
        if start > end:
            skip.append(c)
            continue
        plan.append((c, start, end))
    if limit:
        plan = plan[:limit]
    if not quiet:
        head = f"待更新 {len(plan)} 只（区间 {plan[0][1]}~{end} 起）· 已最新 {len(skip)} 只"
        print(head + (f" · 其中 {len(pend & set(targets))} 只是上轮没补上的" if pend else ""))
    if dry_run or not plan:
        return {"n_targets": len(plan), "n_ok": 0, "n_fail": 0, "new_bars": 0,
                "fail": [], "unsupported": [], "aborted": None}

    _ping()
    got, fail, warn, unsupported = {}, [], [], []
    ok_codes = set()                 # 这次明确抓取成功的票（含停牌返回空的）
    n_with_bars, new_bars = 0, 0     # 跨批累计：got 每写一批就清空
    n_flush = 0                      # 只有第一批写入前拍快照
    n_fetch_ok = 0
    t_begin = dt.datetime.now()
    t0 = time.time()

    # 探针：整源不可用时（源端报错、被限流），别把 1500 只票逐个试一遍。
    # 实测一次全量"逐个失败"能烧掉几小时，而库里数据其实一根都没变。
    # 探针必须是通道取得到的票（_pick_probe），否则一只北交所代码就能让整轮中止。
    rest = list(plan)
    pi = _pick_probe(plan)
    if pi is not None:
        c0, s0, e0 = rest.pop(pi)
        try:
            r0 = _fetch_range(c0, s0, e0)
        except Exception as e:                               # noqa: BLE001
            thr = _is_throttle(e)
            _log({"kind": "update_abort", "probe": c0, "reason": repr(e)[:160],
                  "throttled": thr, "n_targets": len(plan)})
            if thr:
                raise SystemExit(
                    f"服务端持续限流（{c0} 重试 {_THROTTLE_RETRIES} 次仍被拒），本次更新已中止；"
                    f"库里数据未改动。\n当前请求间隔已放到 {_PACE['gap']:.1f} 秒。"
                    "稍后重试，或降并发：python3 market_data.py update --workers 2") from None
            raise SystemExit(f"数据源不可用（{str(e)[:120]}），本次更新已中止；库里数据未改动。"
                             "\n稍后重试：python3 market_data.py update") from None
        n_fetch_ok += 1
        ok_codes.add(c0)
        n_with_bars += _collect(c0, r0, st, got, warn)

    streak, thr_streak, max_streak = 0, 0, max(6, workers * 3)
    aborted = None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_range, c, s, e): (c, s) for c, s, e in rest}
        for n, fu in enumerate(as_completed(futs), 1):
            c, s = futs[fu]
            try:
                r = fu.result()
                n_fetch_ok += 1
                ok_codes.add(c)
                streak = thr_streak = 0
                n_with_bars += _collect(c, r, st, got, warn)
            except Exception as e:                           # noqa: BLE001
                if _channel_unsupported(c, e):
                    # 通道不支持这只票：既不是失败也不进待补清单（否则每晚排最前、
                    # 永远补不上），更不能算进熔断——它说明不了源端状态。
                    unsupported.append(c)
                    continue
                thr = _is_throttle(e)
                fail.append({"code": c, "err": repr(e)[:120], "throttle": thr})
                if thr:
                    # 限流有明确原因、也会自己恢复，不能当"源端故障"熔断——那正是
                    # 连续四晚在 0005xx 收工的机制。但连续这么多只重试后仍被拒，
                    # 说明当晚配额确实用完了，收工并把清单留给明天。
                    streak = 0
                    thr_streak += 1
                    if thr_streak >= max_streak * 2:
                        aborted = "throttled"
                        for f in futs:
                            f.cancel()
                        print(f"⚠ 连续 {thr_streak} 只重试 {_THROTTLE_RETRIES} 次后仍被限流，"
                              f"当晚配额已尽，收工（已处理 {n}/{len(rest)}）")
                        break
                else:
                    thr_streak = 0
                    streak += 1
                    if streak >= max_streak:
                        aborted = "source"
                        for f in futs:
                            f.cancel()
                        print(f"⚠ 连续 {streak} 只失败，判定为源端故障，提前收工"
                              f"（已处理 {n}/{len(rest)}）")
                        break
            if len(got) >= flush_every:
                # 写库在 try 之外：写入失败（只增不减守卫、磁盘满）不是"这只票抓取失败"，
                # 不能混进熔断计数、更不能每抓一只就重试一次写。停掉剩下的抓取，原样抛出。
                try:
                    new_bars += _flush(got, quiet, snap=n_flush == 0)
                    n_flush += 1
                except BaseException:
                    for f in futs:
                        f.cancel()
                    raise
            if not quiet and n % 200 == 0:
                print(f"  {n}/{len(rest)} … {time.time()-t0:.0f}s", flush=True)

    out = {"n_targets": len(plan), "n_ok": n_fetch_ok, "n_fail": len(fail),
           "new_bars": 0, "fail": fail, "warn": warn, "aborted": aborted,
           "unsupported": sorted(unsupported),
           "started": t_begin.isoformat(timespec="seconds"),
           "elapsed": round(time.time() - t0, 1),
           "empty": max(0, len(plan) - n_with_bars - len(fail) - len(unsupported))}
    # 失败清单落盘：明天优先补它们，而不是从 000001 重新排、在同一段再撞一次。
    # 必须与旧清单合并——分批跑时后一段的空失败会覆盖前一段的，实测丢过 2 只。
    lag = {f["code"]: (st.get(f["code"]) or {}).get("last") or DEFAULT_START
           for f in fail}
    for c in set(_read_pending()) - ok_codes - set(unsupported):
        if c not in lag and c in st:
            lag[c] = (st.get(c) or {}).get("last") or DEFAULT_START
    _write_pending(lag)
    new_bars += _flush(got, quiet, snap=n_flush == 0)
    out["new_bars"] = new_bars
    _log({"kind": "update",
          **{k: v for k, v in out.items() if k not in ("fail", "unsupported")},
          "fail_n": len(fail), "fail": fail[:20],
          "unsupported_n": len(unsupported), "unsupported": sorted(unsupported)[:20]})
    if not quiet:
        print(f"完成：{out['n_ok']} 只抓取成功、{out['n_fail']} 只失败；"
              f"{n_with_bars} 只有新 bar，新增 {out['new_bars']:,} 行")
        if unsupported:
            print(f"跳过 {len(unsupported)} 只北交所票：MCP 通道取不到，需走 HTTP 通道"
                  "（README §4.1）")
        if warn:
            print(f"⚠ {len(warn)} 只票新旧衔接跳空 >25%，检查复权基准：{[w['code'] for w in warn][:10]}")
    return out


def add(codes, start: str | None = None, workers: int = 4, quiet: bool = False) -> dict:
    """加票：抓全历史（默认从 DEFAULT_START 起），已有则退化为增量。"""
    _ensure()
    codes = [norm_code(c) for c in codes]
    meta = _read_meta()
    st = meta.setdefault("stocks", {})
    start = start or DEFAULT_START
    end = _today()
    _ping()
    got, fail = {}, []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_range, c, start, end): c for c in codes if c not in st}
        for fu in as_completed(futs):
            c = futs[fu]
            try:
                r = fu.result()
                if r.get("bars"):
                    got[c] = {"code": c, "name": r.get("name"), "bars": r["bars"]}
                else:
                    fail.append({"code": c, "err": "返回 0 根 bar"})
            except Exception as e:                           # noqa: BLE001
                fail.append({"code": c, "err": repr(e)[:120]})
    if got:
        ingest(got.values(), source="stock-server/add", quiet=quiet)
        m2 = _read_meta()
        m2["date_range"] = _date_range(m2)
        m2["n_bars"] = _n_bars()
        _write_meta(m2)
    _log({"kind": "add", "codes": codes, "n_ok": len(got), "n_fail": len(fail), "fail": fail[:20]})
    if not quiet:
        print(f"完成：新增 {len(got)} 只、失败 {len(fail)} 只，{time.time()-t0:.0f}s")
    return {"n_ok": len(got), "n_fail": len(fail), "fail": fail}


# ---------------------------------------------------------------- 统计与校验
def _n_bars() -> int:
    tot = 0
    for p in glob.glob(os.path.join(BARS, "*.parquet")):
        tot += int(pq.ParquetFile(p).metadata.num_rows)
    return tot


def check(quiet: bool = False) -> dict:
    """秒级结构体检：分区齐全 / 分区纯度 / meta 行数对账。适合每天 update 之后跑。

    和 `verify` 的分工：`verify` 把全库读进内存逐行查（重复、OHLC 关系、日期单调，
    约 30 秒），适合周度或出事后；`check` 只读 `code`/`date` 两列做算术（约 3 秒），
    查的正是"数据有没有悄悄变少、有没有落错分区"——两类都不会让 OHLC 检查变红。
    """
    meta = _read_meta()
    parts = partition_stats()
    rng = meta.get("date_range") or []
    missing = []
    if len(rng) == 2 and rng[0] and rng[1]:
        want = [str(y) for y in range(int(str(rng[0])[:4]), int(str(rng[1])[:4]) + 1)]
        missing = [y for y in want if y not in parts]
    stray = {y: s["stray"] for y, s in parts.items() if s.get("stray")}

    disk: dict[str, int] = {}
    for p in sorted(glob.glob(os.path.join(BARS, "*.parquet"))):
        for c, n in pd.read_parquet(p, columns=["code"])["code"].value_counts().items():
            disk[c] = disk.get(c, 0) + int(n)
    st = meta.get("stocks") or {}
    short = [(c, int(v.get("n_bars") or 0), disk.get(c, 0)) for c, v in st.items()
             if (v.get("n_bars") is not None) and int(v.get("n_bars") or 0) > disk.get(c, 0)]
    over = [c for c, v in st.items()
            if (v.get("n_bars") is not None) and int(v.get("n_bars") or 0) < disk.get(c, 0)]
    short.sort(key=lambda x: x[2] - x[1])
    ok = not missing and not stray and not short
    out = {"ok": ok, "missing_years": missing, "stray": stray,
           "n_short": len(short), "n_over": len(over),
           "short_bars": sum(a - b for _, a, b in short),
           "sample": short[:5], "rows": sum(s["rows"] for s in parts.values()),
           "codes": len(disk), "n_parts": len(parts)}
    if not quiet:
        print(f"分区          {out['n_parts']} 个 / {out['rows']:,} 行 / {out['codes']:,} 只")
        if missing:
            print(f"⚠ 缺分区      {','.join(missing)}——库声明区间内每年都必须有 parquet")
        if stray:
            print(f"⚠ 落错分区    {stray}")
        if short:
            ex = "; ".join(f"{c} 声称 {a} 实际 {b}" for c, a, b in out["sample"])
            print(f"⚠ 行数变少    {len(short)} 只，合计少 {out['short_bars']:,} 根（{ex}）")
            print(f"              回滚：market_data.py restore <stamp>")
        if over:
            print(f"· 行数变多    {len(over)} 只——meta 没重算，跑 rebuild-meta")
        print("结论：" + ("通过" if ok else "有问题，见上"))
    return out


def _date_range(meta: dict | None = None) -> list:
    st = (meta or _read_meta()).get("stocks") or {}
    firsts = [v.get("first") for v in st.values() if v.get("first")]
    lasts = [v.get("last") for v in st.values() if v.get("last")]
    return [min(firsts), max(lasts)] if firsts else []


def status(quiet: bool = False) -> dict:
    meta = _read_meta()
    st = meta.get("stocks") or {}
    parts = sorted(glob.glob(os.path.join(BARS, "*.parquet")))
    size = sum(os.path.getsize(p) for p in parts) / 1e6
    n_bars = _n_bars()
    info = {"n_codes": len(st), "n_bars": n_bars, "partition_mb": round(size, 1),
            "date_range": _date_range(meta), "updated": meta.get("updated"),
            "partitions": [os.path.basename(p) for p in parts]}
    snaps = list_snapshots()
    info["snapshots"] = snaps[:3]
    info["n_snapshots"] = len(snaps)
    # 数据到哪天：最后 5 个有数据的交易日
    if parts:
        last = load(start=(dt.date.today() - dt.timedelta(days=20)).isoformat(),
                    columns=["date", "code"], as_datetime=False)
        cnt = last.groupby("date").size().sort_index()
        info["recent_days"] = [(d, int(n)) for d, n in cnt.tail(5).items()]
        info["stale_days"] = (dt.date.today() - dt.date.fromisoformat(info["date_range"][1])).days
    if not quiet:
        print(f"库位置      {ROOT}")
        print(f"标的 / 行数  {info['n_codes']:,} 只 / {n_bars:,} 行 / {info['partition_mb']} MB")
        print(f"覆盖区间    {info['date_range'][0]} ~ {info['date_range'][1]}"
              f"（距今 {info.get('stale_days')} 天）")
        print(f"最后更新    {meta.get('updated')}")
        if (info.get("stale_days") or 0) > 5:
            print(f"⚠ 数据距今 {info['stale_days']} 天，跑一次 `market_data.py update` 补上")
        if info.get("recent_days"):
            print("最近交易日  " + " · ".join(f"{d}:{n}" for d, n in info["recent_days"]))
        print(f"分区        {', '.join(info['partitions'])}")
        if snaps:
            s = snaps[0]
            print(f"写前快照    {info['n_snapshots']} 份，最近 {s['stamp']}"
                  f"（{len(s['years'])} 个分区 / {s['mb']} MB）"
                  f"  回滚：market_data.py restore {s['stamp']}")
        else:
            print("写前快照    无——第一次 update 会自动建立，也可以先手动 snapshot 一次")
    return info


def verify(deep: bool = False, quiet: bool = False) -> dict:
    """校验：重复 / 单调 / OHLC 关系 / 与 meta 对账 / 分区纯度 / 截面断层。只报告，不改数据。"""
    df = load(as_datetime=True)
    issues = {"dup": 0, "bad_ohlc": 0, "unsorted": 0, "meta_mismatch": [],
              "thin_days": [], "stray": {}}
    if df.empty:
        return issues
    # 时间单调 + 重复：按 code 分组，比较排序前后是否一致
    dup = df.duplicated(["code", "date"]).sum()
    issues["dup"] = int(dup)
    bad = ((df["high"] + 1e-9 < df[["open", "close"]].max(axis=1)) |
           (df["low"] - 1e-9 > df[["open", "close"]].min(axis=1)) |
           (df["high"] < df["low"]))
    issues["bad_ohlc"] = int(bad.sum())
    if deep:
        us = 0
        for _, g in df.groupby("code", sort=False):
            if not g["date"].is_monotonic_increasing:
                us += 1
        issues["unsorted"] = us
    meta = _read_meta().get("stocks") or {}
    g = df.groupby("code")["date"]
    stats = pd.DataFrame({"first": g.min(), "last": g.max(), "n": g.size()})
    for c, r in stats.iterrows():
        m = meta.get(c)
        if not m:
            issues["meta_mismatch"].append({"code": c, "why": "meta 里没有"})
        elif m.get("n_bars") != int(r["n"]) or m.get("last") != str(r["last"].date()):
            issues["meta_mismatch"].append({"code": c, "meta_n": m.get("n_bars"),
                                            "bars_n": int(r["n"]),
                                            "meta_last": m.get("last"),
                                            "bars_last": str(r["last"].date())})
    cnt = df.groupby("date").size()
    med = cnt.median()
    issues["thin_days"] = [(str(d.date()), int(n)) for d, n in cnt[cnt < med * 0.5].items()][-10:]
    # 分区纯度：每根 bar 必须落在文件名那一年。落错分区的行不会让上面任何一项变红
    # （行是真的、OHLC 合法、和 meta 也对得上），但会和其他分区撞成重复，
    # 并在该票序列里插进一个假收益。查它只需读一次 date 列。
    st_parts = partition_stats()
    issues["stray"] = {y: s["stray"] for y, s in st_parts.items() if s.get("stray")}
    ok = (issues["dup"] == 0 and issues["bad_ohlc"] == 0 and issues["unsorted"] == 0
          and not issues["meta_mismatch"] and not issues["stray"])
    issues["ok"] = ok
    if not quiet:
        print(f"重复 (code,date)  {issues['dup']}")
        print(f"OHLC 关系异常     {issues['bad_ohlc']}")
        if deep:
            print(f"日期非单调的票    {issues['unsorted']}")
        print(f"meta 对不上的票   {len(issues['meta_mismatch'])}")
        for x in issues["meta_mismatch"][:5]:
            print("   ", x)
        if issues["stray"]:
            print(f"落错分区的行      {issues['stray']}"
                  "（分区文件名是年份，行必须属于该年）")
        if issues["thin_days"]:
            print(f"截面骤降的日期    {issues['thin_days']}")
        print("结论：" + ("通过" if ok else "有问题，见上"))
    return issues


def rebuild_meta(quiet: bool = False) -> dict:
    """从 parquet 反推每票的 first/last/n_bars（保留 name/行业等元信息）。"""
    meta = _read_meta()
    st = meta.setdefault("stocks", {})
    df = load(columns=["code", "date"], as_datetime=False)
    g = df.groupby("code")["date"]
    stats = pd.DataFrame({"first": g.min(), "last": g.max(), "n": g.size()})
    for c, r in stats.iterrows():
        e = st.setdefault(c, {"name": c})
        e["first"], e["last"], e["n_bars"] = str(r["first"]), str(r["last"]), int(r["n"])
    meta["stocks"] = {c: e for c, e in st.items() if c in stats.index}
    meta["date_range"] = _date_range(meta)
    meta["n_bars"] = int(len(df))
    _write_meta(meta)
    if not quiet:
        print(f"meta 重建：{len(stats)} 只 / {len(df):,} 行")
    return meta


def import_ss_cache(src: str, quiet: bool = False) -> dict:
    """从 factor_lab 的 `data/ss_cache/*.json` 一次性迁移（保留名称/板块/申万行业）。"""
    files = sorted(glob.glob(os.path.join(src, "*.json")))
    if not files:
        raise SystemExit(f"{src} 下没有 json")
    _ensure()

    def rec(f):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        return {"code": d["code"], "name": d.get("name") or d.get("ss_name"),
                "board": d.get("board"), "list_date": d.get("list_date"),
                "sw1": d.get("sw1"), "sw3": d.get("sw_l3"),
                "sw_l3_code": d.get("sw_l3_code"),
                "n_bars": len(d.get("bars") or []),
                "bars": d.get("bars") or []}

    batch, out = [], {"stocks": 0, "bars": 0}
    for f in files:
        batch.append(rec(f))
        if len(batch) >= 200:
            # protect=False：一次迁移会触碰全部 13 个分区、连做几十批，
            # 逐批快照等于把同一个分区钉 8 次；源 json 本身还在，回滚靠它。
            r = ingest(batch, source="ss_cache", quiet=True, protect=False)
            out["stocks"] += len(batch); out["bars"] += r["n_bars"]; batch = []
    if batch:
        r = ingest(batch, source="ss_cache", quiet=True, protect=False)
        out["stocks"] += len(batch); out["bars"] += r["n_bars"]
    m = _read_meta()
    m["date_range"] = _date_range(m)
    m["n_bars"] = _n_bars()
    m["source"] = "stock-server query_stock_quote(adjust=hfq)，经 ss_cache 迁移"
    _write_meta(m)
    _log({"kind": "import_ss_cache", "src": src, **out})
    if not quiet:
        print(f"迁移 {out['stocks']} 只 / {out['bars']:,} 行")
    return out


# ---------------------------------------------------------------- 导出
def export(out: str, codes=None, start=None, end=None, field: str | None = None) -> str:
    if out.endswith(".csv"):
        df = (panel(field, codes, start, end).reset_index() if field
              else load(codes, start, end))
        df.to_csv(out, index=False, encoding="utf-8-sig")
    elif out.endswith(".parquet"):
        df = load(codes, start, end, as_datetime=False)
        df.to_parquet(out, index=False, compression="zstd")
    else:
        raise SystemExit("只支持 .csv / .parquet")
    print(f"导出 {len(df):,} 行 → {out}")
    return out


# ---------------------------------------------------------------- CLI
def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="本地 A 股行情库（后复权日线）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="覆盖范围 / 最新交易日 / 分区")

    pu = sub.add_parser("update", help="增量更新（只补上次之后的新 bar）")
    pu.add_argument("--codes", nargs="*")
    pu.add_argument("--workers", type=int, default=6)
    pu.add_argument("--end")
    pu.add_argument("--dry-run", action="store_true")
    pu.add_argument("--limit", type=int, help="只处理前 N 只（冒烟测试用）")

    pa_ = sub.add_parser("add", help="加票（补全历史；已有则增量）")
    pa_.add_argument("codes", nargs="+")
    pa_.add_argument("--start")
    pa_.add_argument("--workers", type=int, default=4)

    pv = sub.add_parser("verify", help="完整性校验")
    pv.add_argument("--deep", action="store_true")

    pck = sub.add_parser("check", help="秒级结构体检（分区齐全/纯度/行数对账）")
    pck.add_argument("--quiet", action="store_true")

    ps = sub.add_parser("snapshot", help="给分区留一份硬链接快照（几乎不占空间）")
    ps.add_argument("--years", nargs="*", help="默认全部已存在的分区")
    ps.add_argument("--tag", default="manual")
    ps.add_argument("--keep", type=int, default=SNAP_KEEP, help=f"保留最近几份（默认 {SNAP_KEEP}）")

    psl = sub.add_parser("snapshots", help="列出已有快照")

    pr = sub.add_parser("restore", help="从快照恢复分区（恢复前会先备份当前状态）")
    pr.add_argument("stamp")
    pr.add_argument("--years", nargs="*")

    pe = sub.add_parser("export", help="导出 csv / parquet")
    pe.add_argument("--out", required=True)
    pe.add_argument("--codes", nargs="*")
    pe.add_argument("--start")
    pe.add_argument("--end")
    pe.add_argument("--field", help="给该字段导宽表（日期 × 代码）")

    pm = sub.add_parser("rebuild-meta", help="从 parquet 反推 meta")
    pm.add_argument("--quiet", action="store_true")

    pi = sub.add_parser("import", help="从 factor_lab/data/ss_cache 迁移旧缓存")
    pi.add_argument("src")

    a = p.parse_args(argv)
    if a.cmd == "status":
        status()
    elif a.cmd == "update":
        r = update(codes=a.codes, workers=a.workers, end=a.end, dry_run=a.dry_run,
                   limit=a.limit)
        # 熔断/限流收工必须让退出码非 0。原来这里恒为 0，定时任务看到的永远是
        # "成功"——11-02~11-05 连续四晚只跑 47/1524 只，日志一片绿。
        if r.get("aborted"):
            sys.exit(2)
    elif a.cmd == "add":
        r = add(a.codes, start=a.start, workers=a.workers)
        # 同样别把失败吞成 0：update.sh 靠这个退出码判断 pending_add.txt 里的票
        # 该不该留在待办里，恒 0 会让它每次都"补齐成功"地把票删掉。
        if r["n_fail"]:
            sys.exit(2)
    elif a.cmd == "verify":
        verify(deep=a.deep)
    elif a.cmd == "check":
        sys.exit(0 if check(quiet=a.quiet)["ok"] else 2)
    elif a.cmd == "snapshot":
        snapshot(a.years, tag=a.tag, keep=a.keep, quiet=False)
    elif a.cmd == "snapshots":
        ss = list_snapshots()
        if not ss:
            print("还没有快照。`market_data.py snapshot` 建一份。")
        else:
            sp = _snapshot_space()
            print(f"共 {sp['dirs']} 份 / {sp['files']} 个文件，**真实独占 {sp['own_mb']:.0f} MB**"
                  f"（{sp['own_files']} 个文件硬链接已被替换掉）")
            print("（own 是该份独占的空间，只有被真正替换过的分区才占；mb 是表观大小，别拿它算成本）")
        for s in ss:
            print(f"{s['stamp']}  {len(s['years'])} 个分区 / 表观 {s['mb']} MB / "
                  f"独占 {s['own_mb']} MB  {','.join(s['years'])}")
    elif a.cmd == "restore":
        restore(a.stamp, years=a.years)
    elif a.cmd == "export":
        export(a.out, a.codes, a.start, a.end, a.field)
    elif a.cmd == "rebuild-meta":
        rebuild_meta(quiet=a.quiet)
    elif a.cmd == "import":
        import_ss_cache(a.src)


if __name__ == "__main__":
    main()
