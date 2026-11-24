# -*- coding: utf-8 -*-
"""行情库的自检（不联网）。运行：python3 test_market_data.py

覆盖的是"写入 → 读取 → 去重 → 增量 → 面板 → 校验"这条链上最容易静默出错的地方：
重复写入会不会把行数翻倍、同一天的数据会不会保留旧值、跨年分区会不会错位、
坏数据能不能被 verify 抓出来。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

TMP = tempfile.mkdtemp(prefix="market_data_test_")
os.environ["MARKET_DATA_HOME"] = TMP          # 必须在 import 之前设，模块级常量会读它
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import market_data as md                      # noqa: E402
import fix_adjbreaks as fx                    # noqa: E402

import numpy as np                            # noqa: E402
import pandas as pd                           # noqa: E402


def rec(code, rows, name=None, **kw):
    return {"code": code, "name": name or code,
            "bars": [{"d": d, "o": o, "h": h, "l": lo, "c": c,
                      "v": 100.0, "amt": 1000.0, "f": 1.0, "trd": 1}
                     for d, o, h, lo, c in rows], **kw}


class T(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(md.BARS, ignore_errors=True)
        shutil.rmtree(md.SNAP, ignore_errors=True)
        os.makedirs(md.BARS, exist_ok=True)
        for p in (md.META, md.LOG, md.PENDING_UPDATE):
            if os.path.exists(p):
                os.remove(p)

    # ---------------------------------------------------------------- 基础
    def test_norm_code(self):
        self.assertEqual(md.norm_code("600519.SH"), "600519")
        self.assertEqual(md.norm_code("sh600519"), "600519")
        self.assertEqual(md.norm_code("sz000001"), "000001")
        self.assertEqual(md.norm_code("1"), "000001")
        self.assertEqual(md.norm_code(" 000002 "), "000002")

    def test_roundtrip(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)]),
                   rec("000001", [("2024-01-02", 10, 11, 9, 10.5)])])
        df = md.load()
        self.assertEqual(len(df), 3)
        self.assertEqual(list(df.columns), md.ORDER)
        self.assertTrue(str(df["date"].dtype).startswith("datetime64"))
        self.assertEqual(set(df["code"]), {"000001", "600000"})
        # 排序：code 升序，同日按日期
        self.assertEqual(df["code"].tolist(), ["000001", "600000", "600000"])

    def test_reingest_does_not_duplicate(self):
        r = rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                           ("2024-01-03", 1.5, 2.5, 1, 2)])
        md.ingest([r])
        md.ingest([r])                       # 同一批数据再写一次
        self.assertEqual(len(md.load()), 2)

    def test_same_day_keeps_last(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 9.9)])])   # 修正值
        df = md.load()
        self.assertEqual(len(df), 1)
        self.assertAlmostEqual(float(df["close"].iloc[0]), 9.9)

    def test_partition_by_year(self):
        md.ingest([rec("600000", [("2023-12-29", 1, 2, 0.5, 1.5),
                                  ("2024-01-02", 1.5, 2.5, 1, 2)])])
        files = sorted(os.path.basename(p) for p in md.glob_files()) \
            if hasattr(md, "glob_files") else \
            sorted(f for f in os.listdir(md.BARS) if f.endswith(".parquet"))
        self.assertEqual(files, ["2023.parquet", "2024.parquet"])

    def test_meta_reflects_content(self):
        md.ingest([rec("600000", [("2023-12-29", 1, 2, 0.5, 1.5),
                                  ("2024-01-02", 1.5, 2.5, 1, 2)], name="浦发银行")])
        m = md._read_meta()
        e = m["stocks"]["600000"]
        self.assertEqual(e["name"], "浦发银行")
        self.assertEqual((e["first"], e["last"], e["n_bars"]), ("2023-12-29", "2024-01-02", 2))
        self.assertEqual(m["n_codes"], 1)

    # ---------------------------------------------------------------- 读
    def test_panel_shape_and_index(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)]),
                   rec("000001", [("2024-01-02", 10, 11, 9, 10.5),
                                  ("2024-01-03", 10.5, 12, 10, 11)])])
        p = md.panel("close")
        self.assertEqual(p.shape, (2, 2))
        self.assertEqual(list(p.columns), ["000001", "600000"])
        self.assertAlmostEqual(float(p.loc["2024-01-03", "600000"]), 2.0)

    def test_load_filters(self):
        md.ingest([rec("600000", [("2023-12-29", 1, 2, 0.5, 1.5),
                                  ("2024-01-02", 1.5, 2.5, 1, 2),
                                  ("2024-01-03", 1.5, 2.5, 1, 2.2)])])
        self.assertEqual(len(md.load(start="2024-01-01")), 2)
        self.assertEqual(len(md.load(end="2024-01-02")), 2)
        self.assertEqual(len(md.load(codes=["600000.SH"], start="2024-01-03")), 1)
        self.assertEqual(len(md.load(codes=["000001"])), 0)

    def test_empty_library_raises(self):
        with self.assertRaises(FileNotFoundError):
            md.load()

    # ---------------------------------------------------------------- 校验
    def test_verify_catches_bad_ohlc(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        md.ingest([rec("600000", [("2024-01-02", 1, 0.4, 0.9, 1.5)])])   # high < low
        v = md.verify(quiet=True)
        self.assertGreaterEqual(v["bad_ohlc"], 1)
        self.assertFalse(v["ok"])

    def test_verify_catches_meta_mismatch(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        m = md._read_meta()
        m["stocks"]["600000"]["n_bars"] = 99                  # 人为把 meta 改坏
        md._write_meta(m)
        v = md.verify(quiet=True)
        self.assertEqual(len(v["meta_mismatch"]), 1)

    def test_rebuild_meta_repairs(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)])])
        m = md._read_meta()
        m["stocks"]["600000"]["n_bars"] = 99
        md._write_meta(m)
        md.rebuild_meta(quiet=True)
        self.assertEqual(md._read_meta()["stocks"]["600000"]["n_bars"], 2)

    # ---------------------------------------------------------------- 写入守卫
    def test_ingest_refuses_to_recreate_existing_partition(self):
        """一次 `add` 曾经把 2014 分区整块顶掉（968 只票 / 138,975 行消失）。

        复现条件：分区文件在写入那一刻不存在（被删/路径不对/替换中途），
        代码走"新建分区"分支，把本批数据当成整年数据写回去，旧行永久消失
        且不报错。守卫要求：元信息里的库区间内，每一年都必须有分区文件；
        只有"往更早年份扩历史"或"新年度第一天"才允许新建。
        """
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)]),
                   rec("000001", [("2024-01-02", 10, 11, 9, 10.5)])])
        self.assertEqual(md.load()["code"].nunique(), 2)
        self.assertEqual(md._read_meta()["date_range"], ["2024-01-02", "2024-01-02"])

        os.remove(os.path.join(md.BARS, "2024.parquet"))     # 模拟分区被顶掉
        with self.assertRaises(RuntimeError):
            md.ingest([rec("600001", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        # 守卫拦在写入之前，没有拿"一只新票"覆盖掉整年
        self.assertFalse(os.path.exists(os.path.join(md.BARS, "2024.parquet")))

    def test_ingest_allows_new_year_outside_range(self):
        """新年度的第一天必须能建分区，否则每到 1 月 1 日增量就崩。"""
        md.ingest([rec("600000", [("2024-12-31", 1, 2, 0.5, 1.5)])])
        md.ingest([rec("600000", [("2025-01-02", 1, 2, 0.5, 1.5)])])
        self.assertTrue(os.path.exists(os.path.join(md.BARS, "2025.parquet")))
        self.assertEqual(len(md.load()), 2)

    def test_rebuild_partition_is_the_explicit_escape(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)]),
                   rec("000001", [("2024-01-02", 10, 11, 9, 10.5)])])
        t = md.load()
        keep = t[t["code"] == "600000"].copy()
        md.rebuild_partition("2024", keep)                     # 显式整分区重写
        self.assertEqual(md.load()["code"].unique().tolist(), ["600000"])
        with self.assertRaises(ValueError):
            md.rebuild_partition("2024", keep.iloc[0:0])       # 不许清空

    def test_load_never_shrinks_on_overlapping_reingest(self):
        """同一批数据重写不得让任何一年变小（写入是原子替换，没有第二份）。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)]),
                   rec("000001", [("2024-01-03", 10, 11, 9, 10.5)])])
        before = len(md.load())
        md.ingest([rec("000001", [("2024-01-03", 10, 11, 9, 10.5)])])   # 只重写一只
        self.assertEqual(len(md.load()), before)

    # ---------------------------------------------------------------- 分区纯度
    def test_verify_catches_stray_row(self):
        """落错分区的行不会让其他任何一项变红，只能靠分区纯度抓。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        df = md.load(as_datetime=False)
        df.loc[0, "date"] = "2025-01-02"                 # 塞进 2024 分区
        md.rebuild_partition("2024", df)
        v = md.verify(quiet=True)
        self.assertEqual(v["stray"], {"2024": 1})
        self.assertFalse(v["ok"])

    def test_partition_stats_shape(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)]),
                   rec("000001", [("2024-01-03", 10, 11, 9, 10.5)])])
        s = md.partition_stats()
        self.assertEqual(list(s), ["2024"])
        self.assertEqual((s["2024"]["rows"], s["2024"]["codes"]), (3, 2))
        self.assertEqual((s["2024"]["min"], s["2024"]["max"]), ("2024-01-02", "2024-01-03"))
        self.assertEqual(s["2024"]["stray"], 0)

    # ---------------------------------------------------------------- 写前快照
    def test_snapshot_is_hardlink(self):
        """硬链接而不是复制：省空间，且 os.replace 后旧 inode 仍完好。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        r = md.snapshot(quiet=True)
        self.assertEqual(r["linked"], 1)
        self.assertEqual(r["copied"], 0)
        src = os.path.join(md.BARS, "2024.parquet")
        dst = os.path.join(md.SNAP, r["stamp"], "2024.parquet")
        self.assertEqual(os.stat(src).st_ino, os.stat(dst).st_ino)

    def test_snapshot_copies_when_asked(self):
        """MD_SNAPSHOT_COPY=1（平台里跑）：复制，不留第二个链接——平台的数据检查点拒收 nlink>1 的文件。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        os.environ["MD_SNAPSHOT_COPY"] = "1"
        self.addCleanup(os.environ.pop, "MD_SNAPSHOT_COPY", None)
        r = md.snapshot(quiet=True)
        self.assertEqual((r["linked"], r["copied"]), (0, 1))
        src = os.path.join(md.BARS, "2024.parquet")
        dst = os.path.join(md.SNAP, r["stamp"], "2024.parquet")
        self.assertNotEqual(os.stat(src).st_ino, os.stat(dst).st_ino)
        self.assertEqual(os.stat(src).st_nlink, 1)

    def test_snapshot_skips_years_that_do_not_exist(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        r = md.snapshot(["2019", "2024"], quiet=True)
        self.assertEqual(r["years"], ["2024"])

    def test_snapshot_keeps_last_n(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        stamps = []
        for i in range(4):
            stamps.append(md.snapshot(quiet=True, keep=2)["stamp"])
        alive = [s["stamp"] for s in md.list_snapshots()]
        self.assertEqual(len(alive), 2)
        self.assertEqual(set(alive), set(stamps[-2:]))   # 留最新的两份

    def test_snapshot_empty_years_takes_nothing(self):
        """空列表 = 没有分区要保护，什么都不拍；None 才是"全部"。

        原来写成 `if years`，空列表走 falsy 分支拍全库。一次空写入就会给 13 个
        分区各建一个硬链接，2026-11-10 积到 87 份、2.4 GB，其中 78 份内容与当前
        bars 完全同一 inode——回滚它们等于原地不动。
        """
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        n0 = len(md.list_snapshots())
        r = md.snapshot([], quiet=True)
        self.assertIsNone(r["stamp"])
        self.assertEqual(r["years"], [])
        self.assertEqual(len(md.list_snapshots()), n0)

    def test_prune_really_deletes_and_reports_space(self):
        """清理必须"真删"，并且把释放的空间报出来（名义 mb 在硬链接下是虚的）。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        stamps = [md.snapshot(quiet=True, keep=1)["stamp"] for _ in range(3)]
        alive = [s["stamp"] for s in md.list_snapshots()]
        self.assertEqual(alive, [stamps[-1]])
        for s in stamps[:-1]:                          # 目录要真的消失，不是"报了删"
            self.assertFalse(os.path.exists(os.path.join(md.SNAP, s)), s)

    def test_prune_raises_when_delete_is_blocked(self):
        """删不掉就报错，绝不静默。

        真实事故：`shutil.rmtree(..., ignore_errors=True)` 在受限环境被拒时异常
        被吞，函数照样把 stamp 塞进 gone、日志照样打"清理了 N 份"。结果快照只增
        不减，一路涨到 87 份 / 2.4 GB，全程没有任何报错。
        """
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        for _ in range(3):
            md.snapshot(quiet=True, keep=99)
        orig = shutil.rmtree
        shutil.rmtree = lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied"))
        try:
            with self.assertRaises(RuntimeError):
                md._prune_snapshots(keep=1, quiet=True)
        finally:
            shutil.rmtree = orig

    def test_ingest_auto_snapshots_and_logs_fingerprint(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        snap = md.snapshot(quiet=True)                    # 先摆一份底
        md.ingest([rec("600000", [("2024-01-03", 1.5, 2.5, 1, 2)])])
        recs = [json.loads(l) for l in open(md.LOG, encoding="utf-8")]
        snaps = [r for r in recs if r["kind"] == "snapshot"]
        self.assertGreaterEqual(len(snaps), 1)
        self.assertIn("parts", snaps[-1])                 # 写前指纹一起落日志
        self.assertEqual(snaps[-1]["parts"]["2024"], [1, 1])
        self.assertTrue(any(s["stamp"] == snap["stamp"] for s in md.list_snapshots()))

    # ---------------------------------------------------------------- 回滚
    def test_restore_brings_partition_back(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)]),
                   rec("000001", [("2024-01-03", 10, 11, 9, 10.5)])])
        snap = md.snapshot(quiet=True)
        keep = md.load()
        md.rebuild_partition("2024", keep[keep["code"] == "600000"])   # 少了一只票
        self.assertEqual(md.load()["code"].nunique(), 1)

        md.restore(snap["stamp"], quiet=True)
        self.assertEqual(md.load()["code"].nunique(), 2)              # 回来了
        self.assertEqual(md._read_meta()["stocks"]["000001"]["n_bars"], 1)

    def test_restore_saves_current_state_first(self):
        """恢复本身也是写操作：先把当前状态钉一份，免得"恢复错了没得退"。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        snap = md.snapshot(quiet=True)
        before = len(md.list_snapshots())
        md.restore(snap["stamp"], quiet=True)
        after = md.list_snapshots()
        self.assertEqual(len(after), before + 1)
        self.assertTrue(any("before-restore" in s["stamp"] for s in after))

    def test_restore_unknown_stamp_raises(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        with self.assertRaises(SystemExit):
            md.restore("19990101-000000")

    # ---------------------------------------------------------------- 报警
    def test_diff_stats_only_reports_shrink(self):
        before = {"2024": {"rows": 3, "codes": 2}, "2023": {"rows": 5, "codes": 4}}
        after = {"2024": {"rows": 4, "codes": 2},     # 变多：正常
                 "2023": {"rows": 5, "codes": 3}}     # 丢票：报警
        d = md._diff_stats(before, after)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["year"], "2023")
        self.assertEqual(d[0]["codes"], [4, 3])

    def test_new_partitions_is_the_choke_point(self):
        """扩池脚本直接调 `_new_partitions`，不走 ingest——防线必须也在那里。

        否则最大的那次写入（1,449 只新票、13 个分区）恰好没有快照，
        而它正是最容易把旧数据整块顶掉的地方。
        """
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        import pandas as pd
        df = pd.DataFrame([("000001", "2024-01-03", 10, 11, 9, 10.5, 100.0, 1000.0, 1.0, 1)],
                          columns=md.ORDER)
        md._new_partitions(df, tag="expand", protect=True)
        stamps = [s["stamp"] for s in md.list_snapshots()]
        self.assertTrue(any("expand" in s for s in stamps))
        self.assertEqual(md.load()["code"].nunique(), 2)

    # ---------------------------------------------------------------- 秒级体检
    def test_check_passes_on_clean_library(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)])])
        r = md.check(quiet=True)
        self.assertTrue(r["ok"])
        self.assertEqual((r["rows"], r["codes"], r["n_parts"]), (2, 1, 1))

    def test_check_catches_shrunk_rows(self):
        """check 要抓的是"行数悄悄变少"——OHLC 和重复都查不出来的那类。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)])])
        df = md.load(as_datetime=False)
        md.rebuild_partition("2024", df.iloc[:1])          # 少了一根，meta 还写着 2
        r = md.check(quiet=True)
        self.assertFalse(r["ok"])
        self.assertEqual(r["n_short"], 1)
        self.assertEqual(r["short_bars"], 1)
        self.assertEqual(r["sample"][0][:2], ("600000", 2))

    def test_check_catches_missing_year(self):
        """库声明区间内的分区凭空消失，是 2014 那次事故的形状。"""
        md.ingest([rec("600000", [("2023-12-29", 1, 2, 0.5, 1.5),
                                  ("2024-01-02", 1.5, 2.5, 1, 2)])])
        os.remove(os.path.join(md.BARS, "2023.parquet"))
        r = md.check(quiet=True)
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing_years"], ["2023"])

    def test_check_ignores_extra_rows_but_flags_meta(self):
        """磁盘比 meta 多是"没重算"，只提示不判失败——和"变少"必须分开。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        m = md._read_meta()
        m["stocks"]["600000"]["n_bars"] = 1
        md._write_meta(m)
        md.ingest([rec("600000", [("2024-01-03", 1.5, 2.5, 1, 2)])], protect=False)
        m = md._read_meta()
        m["stocks"]["600000"]["n_bars"] = 1               # 人为落后
        md._write_meta(m)
        r = md.check(quiet=True)
        self.assertEqual((r["n_short"], r["n_over"]), (0, 1))
        self.assertTrue(r["ok"])

    # ---------------------------------------------------------------- 增量语义
    def test_update_takes_snapshot_before_write(self):
        """日常 update 是最频繁的写路径，必须也能回滚。不联网：把取数打桩。"""
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        real_fetch, real_ping = md._fetch_range, md._ping
        md._ping = lambda: None
        md._fetch_range = lambda c, s, e: {
            "code": c, "name": c,
            "bars": [{"d": "2024-01-03", "o": 1.5, "h": 2.5, "l": 1, "c": 2,
                      "v": 100.0, "amt": 200.0, "trd": 1, "f": 1.0}]}
        try:
            out = md.update(codes=["600000"], end="2024-01-03", quiet=True)
        finally:
            md._fetch_range, md._ping = real_fetch, real_ping
        self.assertEqual(out["new_bars"], 1)
        snaps = md.list_snapshots()
        self.assertEqual(len(snaps), 1)
        self.assertIn("stock-server_update", snaps[0]["stamp"])   # 标签说明了是谁写的
        self.assertEqual(len(md.load()), 2)

    # ---------------------------------------------------------------- 限流与退出码
    def test_throttle_detection(self):
        self.assertTrue(md._is_throttle(RuntimeError("请求失败(429): Too Many Requests")))
        self.assertTrue(md._is_throttle(RuntimeError("HTTP Error 429: Too Many Requests")))
        self.assertFalse(md._is_throttle(RuntimeError("数据源报错：连接超时")))

    def test_throttle_does_not_trip_breaker(self):
        """429 是"服务端在拒"，不是"某只票坏了"，不能拿它当源端故障熔断。

        真实事故：2026-11-02~11-05 连续四晚都在 0005xx 这段被限流截断，
        每晚只跑 47/1524 只就"提前收工"，退出码却是 0，238 只票停在 10-30。
        """
        md.ingest([rec(f"6000{i:02d}", [("2024-01-02", 1, 2, 0.5, 1.5)])
                   for i in range(16)])
        real_fetch, real_ping = md._fetch_range, md._ping
        md._ping = lambda: None

        def fake(c, s, e):
            if c == "600000":                       # 探针要过一次，否则直接中止
                return {"code": c, "name": c, "bars": []}
            raise RuntimeError("数据源报错：执行失败: 请求失败(429): Too Many Requests")

        md._fetch_range = fake
        try:
            out = md.update(end="2024-01-03", workers=3, quiet=True)
        finally:
            md._fetch_range, md._ping = real_fetch, real_ping
        # workers=3 → 熔断阈值 9。把 429 计入 streak 的话，第 10 只就该收工；
        # 现在只有连续 18 只"限流耗尽"才收工，这里 15 只，所以一路跑完。
        self.assertIsNone(out["aborted"])
        self.assertEqual(len(out["fail"]), 15)
        self.assertTrue(all(f["throttle"] for f in out["fail"]))
        self.assertEqual(len(md._read_pending()), 15)          # 失败清单落盘

    def test_pending_list_runs_first(self):
        """没补上的票必须排最前，否则每天从 000001 重排、在同一段再撞一次限流。"""
        md.ingest([rec(f"6000{i:02d}", [("2024-01-02", 1, 2, 0.5, 1.5)])
                   for i in range(4)])
        md._write_pending({"600003": "2024-01-02", "600001": "2024-01-02"})
        seen = []
        real_fetch, real_ping = md._fetch_range, md._ping
        md._ping = lambda: None
        md._fetch_range = lambda c, s, e: (seen.append(c)
                                           or {"code": c, "name": c, "bars": []})
        try:
            md.update(end="2024-01-03", workers=1, quiet=True)
        finally:
            md._fetch_range, md._ping = real_fetch, real_ping
        # 探针（流动性好的锚点票）先跑一只，紧接着就是待补清单
        self.assertEqual(seen[0], "600000")
        self.assertEqual(seen[1:3], ["600001", "600003"])

    # ---------------------------------------------------------------- 北交所与探针
    def _run_update(self, fake, **kw):
        seen = []
        real_fetch, real_ping = md._fetch_range, md._ping
        md._ping = lambda: None

        def rec_fake(c, s, e):
            seen.append(c)
            return fake(c, s, e)

        md._fetch_range = rec_fake
        try:
            return md.update(end="2024-01-03", quiet=True, **kw), seen
        finally:
            md._fetch_range, md._ping = real_fetch, real_ping

    @staticmethod
    def _mcp_like(c, s, e):
        """MCP 通道的真实行为：北交所代码直接报"无法识别交易所"。"""
        if md._is_bse(c):
            raise RuntimeError(f"数据源报错：无法识别股票代码 {c} 的交易所")
        return {"code": c, "name": c, "bars": []}

    def test_is_bse(self):
        for c in ("920001", "830799", "873223", "430047"):
            self.assertTrue(md._is_bse(c), c)
        for c in ("600519", "000001", "300750", "688981", "900901", "200002"):
            self.assertFalse(md._is_bse(c), c)

    def test_probe_is_never_a_bse_code(self):
        """2026-11-23 生产事故：上轮没补上的北交所代码排在最前，探针取 plan[0]
        → MCP 报"无法识别交易所" → 整轮 5,589 只中止。探针必须选通道取得到的票。"""
        codes = ["920001", "920002", "300750", "000001", "600519"]
        md.ingest([rec(c, [("2024-01-02", 1, 2, 0.5, 1.5)]) for c in codes])
        md._write_pending({"920001": "2024-01-02", "920002": "2024-01-02",
                           "300750": "2024-01-02"})
        out, seen = self._run_update(self._mcp_like, workers=1)
        self.assertEqual(seen[0], "600519")            # 优先流动性好的主板票
        self.assertIsNone(out["aborted"])
        self.assertEqual(out["n_fail"], 0)
        self.assertEqual(sorted(out["unsupported"]), ["920001", "920002"])
        # 通道取不到的票不进待补清单：否则每晚排最前、永远补不上
        self.assertEqual(md._read_pending(), [])

    def test_bse_skips_do_not_trip_breaker(self):
        codes = [f"9200{i:02d}" for i in range(20)] + ["600000"]
        md.ingest([rec(c, [("2024-01-02", 1, 2, 0.5, 1.5)]) for c in codes])
        out, _ = self._run_update(self._mcp_like, workers=1)   # 熔断阈值 6
        self.assertIsNone(out["aborted"])
        self.assertEqual(len(out["unsupported"]), 20)
        self.assertEqual(out["fail"], [])

    def test_only_bse_codes_does_not_abort(self):
        md.ingest([rec(c, [("2024-01-02", 1, 2, 0.5, 1.5)]) for c in ("920001", "830799")])
        out, _ = self._run_update(self._mcp_like, workers=1)
        self.assertIsNone(out["aborted"])
        self.assertEqual(sorted(out["unsupported"]), ["830799", "920001"])

    def test_probe_source_failure_still_aborts(self):
        """整源故障（源端报错、限流）仍由探针一次判定并中止，不逐只试一遍。"""
        md.ingest([rec(c, [("2024-01-02", 1, 2, 0.5, 1.5)]) for c in ("920001", "600000")])

        def down(c, s, e):
            raise RuntimeError("数据源报错：连接超时")

        seen = []

        def down_seen(c, s, e):
            seen.append(c)
            return down(c, s, e)

        real_fetch, real_ping = md._fetch_range, md._ping
        md._ping, md._fetch_range = (lambda: None), down_seen
        try:
            with self.assertRaises(SystemExit):
                md.update(end="2024-01-03", workers=1, quiet=True)
        finally:
            md._fetch_range, md._ping = real_fetch, real_ping
        self.assertEqual(seen, ["600000"])             # 探针是主板票，且只试了一只

    def test_bse_skips_do_not_mask_an_outage(self):
        """北交所跳过既不累加也不清零熔断计数：穿插着 920xxx 的真故障照样熔断。"""
        main = [f"6000{i:02d}" for i in range(1, 9)]
        bse = [f"9200{i:02d}" for i in range(8)]
        md.ingest([rec(c, [("2024-01-02", 1, 2, 0.5, 1.5)])
                   for c in ["600000"] + main + bse])

        def outage(c, s, e):
            if c == "600000":
                return {"code": c, "name": c, "bars": []}
            return self._mcp_like(c, s, e) if md._is_bse(c) else (_ for _ in ()).throw(
                RuntimeError("数据源报错：连接超时"))

        out, _ = self._run_update(outage, workers=1)   # 熔断阈值 6
        self.assertEqual(out["aborted"], "source")

    def test_unrecognized_exchange_on_main_board_is_a_failure(self):
        """只有北交所代码的"无法识别交易所"算通道不支持；主板票报这个是真故障。"""
        md.ingest([rec(c, [("2024-01-02", 1, 2, 0.5, 1.5)]) for c in ("600000", "600001")])

        def odd(c, s, e):
            if c == "600001":
                raise RuntimeError(f"数据源报错：无法识别股票代码 {c} 的交易所")
            return {"code": c, "name": c, "bars": []}

        out, _ = self._run_update(odd, workers=1)
        self.assertEqual([f["code"] for f in out["fail"]], ["600001"])
        self.assertEqual(out["unsupported"], [])

    def test_pending_roundtrip(self):
        md._write_pending({"600519": "2026-10-30", "000001": "2026-11-01"})
        self.assertEqual(md._read_pending(), ["000001", "600519"])
        md._write_pending({})
        self.assertEqual(md._read_pending(), [])

    def test_pending_survives_multiple_batches(self):
        """分批跑时，后一段没失败不该把前一段的失败清单冲掉——实测这样丢过 2 只。"""
        md.ingest([rec(f"6000{i:02d}", [("2024-01-02", 1, 2, 0.5, 1.5)])
                   for i in range(4)])
        real_fetch, real_ping = md._fetch_range, md._ping
        md._ping = lambda: None
        md._fetch_range = lambda c, s, e: {"code": c, "name": c, "bars": []}
        try:
            md._write_pending({"600002": "2024-01-02"})
            md.update(codes=["600000"], end="2024-01-03", workers=1, quiet=True)
        finally:
            md._fetch_range, md._ping = real_fetch, real_ping
        self.assertEqual(md._read_pending(), ["600002"])

    def test_pace_gate_serializes(self):
        real = dict(md._PACE)
        try:
            md._PACE.update(gap=0.05, next=0.0, hits=0)
            t = time.time()
            for _ in range(10):
                md._pace_wait()
            self.assertGreaterEqual(time.time() - t, 0.35)      # 9 个间隔约 0.45 秒
        finally:
            md._PACE.clear()
            md._PACE.update(real)

    def test_pace_slows_on_429_but_keeps_floor(self):
        real = dict(md._PACE)
        try:
            md._PACE.update(gap=md._PACE_BASE, next=0.0, hits=0)
            md._pace_slow_down()
            self.assertGreater(md._PACE["gap"], md._PACE_BASE)
            self.assertEqual(md._PACE["hits"], 1)
            for _ in range(500):
                md._pace_speed_up()
            self.assertGreaterEqual(md._PACE["gap"], md._PACE_BASE)   # 不会降到 0
        finally:
            md._PACE.clear()
            md._PACE.update(real)

    def test_incremental_append(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5)])])
        # 模拟"明天又抓到了一根"：只写新 bar，旧 bar 不动
        md.ingest([rec("600000", [("2024-01-03", 1.5, 2.5, 1, 2)])])
        df = md.load()
        self.assertEqual(len(df), 2)
        self.assertEqual(str(df["date"].max().date()), "2024-01-03")
        self.assertEqual(md._read_meta()["stocks"]["600000"]["n_bars"], 2)

    def test_export_csv(self):
        md.ingest([rec("600000", [("2024-01-02", 1, 2, 0.5, 1.5),
                                  ("2024-01-03", 1.5, 2.5, 1, 2)])])
        out = os.path.join(TMP, "x.csv")
        md.export(out, field="close")
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8-sig") as f:
            self.assertEqual(len(f.read().strip().splitlines()), 3)   # 表头 + 2 行

    def test_import_ss_cache(self):
        import json
        src = os.path.join(TMP, "ss")
        os.makedirs(src, exist_ok=True)
        with open(os.path.join(src, "600000.json"), "w", encoding="utf-8") as f:
            json.dump({"code": "600000", "name": "浦发银行", "board": "沪主板",
                       "sw1": "银行", "sw_l3": "股份制银行",
                       "bars": [{"d": "2024-01-02", "o": 1, "h": 2, "l": 0.5,
                                 "c": 1.5, "v": 1, "amt": 1, "trd": 1, "f": 1}]},
                      f, ensure_ascii=False)
        out = md.import_ss_cache(src, quiet=True)
        self.assertEqual(out["stocks"], 1)
        self.assertEqual(md._read_meta()["stocks"]["600000"]["sw1"], "银行")


    # ---------------------------------------------------------------- 复权断点

    @staticmethod
    def _adj(rows):
        """rows = [(close, volume, factor), ...] → 该票的修正倍数 C。"""
        g = pd.DataFrame(rows, columns=["close", "volume", "factor"])
        g["date"] = [f"2020-01-{i + 1:02d}" for i in range(len(rows))]
        return fx._walk(g.sort_values("date"))

    def test_adjbreak_flattens_suspension_and_propagates(self):
        """停牌期间价格不该动。断了就拉平，并把倍数传到后面几行。

        真实病例 600381：2014-06-27 缩股后价格从 17.04 跳到 137.23，而因子一直
        没跟着改。只修那一天，断点会顺移到下一行，所以必须传播。
        """
        C = self._adj([(17.04, 100.0, 8.19),
                       (137.23, 0.0, 8.19),      # 断点：无成交却涨 8 倍
                       (137.23, 0.0, 8.19),
                       (137.23, 0.0, 8.19)])
        self.assertAlmostEqual(C[0], 1.0)
        for c in C[1:]:
            self.assertAlmostEqual(c, 17.04 / 137.23, places=6)
        # 拉平后后复权价连续，真实价不变
        close = np.array([17.04, 137.23, 137.23, 137.23]) * C
        self.assertTrue(np.allclose(close, 17.04, atol=1e-9))
        self.assertTrue(np.allclose(close / (np.array([8.19] * 4) * C),
                                    np.array([17.04, 137.23, 137.23, 137.23]) / 8.19))

    def test_adjbreak_multiplier_released_when_source_catches_up(self):
        """源端自己补上因子时必须撤销补偿。

        真实病例 000007：5 月停牌期间先跌 1/3（因子没动），7 月复牌时源端才把
        factor 8.03→12.05（正好是要补的 ×1.5）。若继续乘我们的 1.5，复牌收益会
        从 −10% 变成 +35%。
        """
        C = self._adj([(191.27, 100.0, 8.03),
                       (127.49, 0.0, 8.03),      # 断点
                       (127.49, 0.0, 8.03),
                       (172.07, 500.0, 12.05)])  # 源端补上因子 + 有成交 → 撤销
        self.assertAlmostEqual(C[1], 191.27 / 127.49, places=6)
        self.assertAlmostEqual(C[2], 191.27 / 127.49, places=6)
        self.assertAlmostEqual(C[3], 1.0)
        # 复牌收益回到真实值：172.07 / (127.49*C) - 1 ≈ −10%
        self.assertAlmostEqual(172.07 / (127.49 * C[2]) - 1, -0.1001, places=3)

    def test_adjbreak_leaves_normal_bars_alone(self):
        """有成交的正常行一律不动——包括真实的重整复牌暴涨。"""
        C = self._adj([(10.0, 100.0, 1.0), (11.0, 100.0, 1.0),
                       (110.0, 100.0, 11.0),      # 真事件：复牌 +900%，因子同步
                       (110.0, 0.0, 11.0)])       # 次日停牌，价格延续，无断点
        self.assertTrue(np.allclose(C, 1.0))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
