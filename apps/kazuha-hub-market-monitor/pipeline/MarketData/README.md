# MarketData · 本地 A 股行情库（后复权日线）

一次下载、永久保存、以后只补增量。研究脚本从这里读数据，不再每次去抓。

- **位置**：`~/MarketData/`（家目录，Finder 可直接看到）
- **规模**：3,499 只 × 9,140,151 根日线，`bars/` 349 MB（`snapshots/` 另占约 304 MB），
  覆盖 **2014-06-03 ~ 2026-11-06**（2026-11-08 核；其中 **169 只是已退市股**，
  `status=delisted`；用 `market_data.py status` 看实时值）
- **来源**：`stock-server` 的 `daily_hfq`，**后复权**
- **依赖**：pandas / numpy / pyarrow（已装）；`update` / `add` 需要 stock-server 在跑，读取不需要

---

## 1. 四条最常用的命令

```bash
python3 ~/MarketData/market_data.py status     # 数据到哪天了、缺不缺
python3 ~/MarketData/market_data.py update     # 增量：只补上次之后的新 bar
python3 ~/MarketData/market_data.py check      # 秒级体检：行数有没有变少、分区有没有落错
python3 ~/MarketData/market_data.py verify     # 全量校验（重复/OHLC/对账），约 30 秒
```

程序里用：

```python
import sys; sys.path.insert(0, "~/MarketData")   # 注意展开 ~ 或写绝对路径
import market_data as md

md.load(codes=["600519", "000001"], start="2020-01-01")   # 长表 DataFrame
md.panel("close", start="2024-01-01")                     # 宽表：日期 × 代码
md.bars_of("600519", start="2025-01-01")                  # 单票
md.universe()                                             # 每票的元信息（名称/板块/行业/首末日期）
```

实测速度（本机、全库 364 万行）：全量 `load()` **0.43 s**，`panel` 近两年 **0.20 s**，
单票全历史 **0.03 s**，近一个月 **0.01 s**。

---

## 2. 数据结构

目录：

```
~/MarketData/
├── market_data.py        库本体 + 命令行（自包含，可整体拷走）
├── update.sh             定时增量（写前快照 + 写后 check，失败会传退出码）
├── test_market_data.py   45 条自检（不联网）
├── bars/YYYY.parquet     按年分区的长表
├── snapshots/            写前快照（硬链接，见 §3.1）
├── meta.json             每票元信息 + 全局统计
├── updates.jsonl         每次更新的审计日志
├── logs/                 每日 update 的完整输出
│
├── 维护脚本（一次性/低频，别放进日常流程）
│   ├── fill_meta.py        元数据补齐（只填空、口径校验、备份；akshare 仅用于元数据）
│   ├── expand_pool.py      扩池缺口清单（四批划分，B 股排除）
│   ├── expand_run.py       扩池补票（pull / ingest 两阶段）
│   ├── repair_2014.py      2014 分区事故的定向修复（pull / ingest 两阶段，已完成）
│   ├── fix_adjbreaks.py    零成交日的复权断点 + denormal 成交额（默认只报告，--apply 才写）
│   ├── pool_source.json    全市场标的来源缓存（expand_pool --offline 用）
│   ├── pool_gap.json       缺口清单（按 A/B/C/D 四批）
│   ├── expand_progress.json 补票进度（断点续跑）
│   ├── meta_source.json    外部元数据映射缓存（可离线复现回填）
│   └── pending_add.txt / pending_update.txt  待补票清单（update.sh 每次重试）
│
├── docs/                 数据层说明与事故复盘（**先读 00-数据字典**）
├── analysis/             分析脚本（读库出结论）+ out/ 结果表
├── backup/               meta.json 的定版备份（bars 有 snapshots，meta 靠这个）
└── README.md             本文件
```

完整文件地图见 §8，数据口径细节见 `docs/00-数据字典.md`。

`bars/*.parquet` 的列：

| 列 | 含义 |
|---|---|
| `code` | 6 位代码，字符串（`000002`，不带后缀） |
| `date` | 交易日 `YYYY-MM-DD`，字符串（ISO 格式，字典序即时间序） |
| `open/high/low/close` | **后复权**价 |
| `volume` | 成交量，**股，但是复权口径**（真实股数 = `volume × factor`） |
| `amount` | 成交额（元，真实值，不受复权影响） |
| `factor` | 累计复权因子，**真实成交价 = close / factor** |
| `tradestatus` | 目前全是 1；**停牌日没有 bar**，不是记 0 |

⚠️ `volume` 有两个坑，用之前先看 `docs/00-数据字典.md`：

1. **它是复权股数**，不是真实股数。平安银行 2026-11-06 存的是 901,283，乘 factor 136.36
   才是真实的 1.23 亿股。直接拿 `volume` 算换手率、算资金流，会差一个 factor 倍数。
2. **`amount / volume` 得到的是后复权价**，不是当日真实成交均价（要真实均价：
   `amount / (volume × factor)`）。

### 为什么是后复权

前复权在**每次新的除权事件**发生后会重算全部历史，增量更新必然对不齐；
后复权只在除权当日对**新数据**缩放，历史 bar 永不改写——这是"增量只 append"能成立的前提。
要还原真实成交价：`df["close"] / df["factor"]`。

---

## 3. 增量更新怎么工作

```
对每只票：start = meta.last + 1 天 → 抓 [start, 今天] → 按年合并去重 → 原子重写该年分区
```

关键设计：

- **只补缺口**，不重下历史。库里已有 2014 年至今，日常更新只拉 1–2 根 bar。
- **以磁盘为准回算元信息**。`n_bars` 不靠"旧值 + 新增"，而是写完分区后重新统计——
  源端重发当天数据时不会重复计数。
- **数据源报错必须炸出来**。源返回 `{"error": ...}` 时抛异常而不是记成"没有新 bar"，
  否则一次服务故障会被静默记成"已是最新"。
- **原子写**。每个分区先写 `.tmp` 再 `os.replace`，中断不会留下半个 parquet。
- **审计日志**。`updates.jsonl` 记录每次的标的数、成功/失败、新增行数、异常票。
- **写前快照 + 写后比对**（见 §3.1）。原子写的好处是没有半个文件，代价是旧数据没有第二份。

交易日 21:00 有一条 launchd 定时任务跑 `update`（见第 6 节「调度与限流」）。

### 3.1 写入保护：三道防线

2026-11-08 出过一次事故：`bars/2014.parquet` 被一批增量当成整年数据写回去，
968 只票的 138,975 根 bar 直接消失，而当时**所有检查都是绿的**。
根因不是某一行代码写错，而是这一层原本只有"原子写"、没有"旧数据还在不在"的概念。
现在三道，从便宜到贵：

| 防线 | 做什么 | 成本 | 拦得住什么 |
|---|---|---|---|
| `partition_stats()` | 写入前后各取一次指纹：行数/票数/日期区间/落错分区的行数 | 全库约 1 秒 | 事后发现，给出准确差额 |
| 硬链接快照 | 写前把**将要改动的分区**钉一份到 `snapshots/<时间戳>-<来源>/` | 微秒级，**空间 0** | 可回滚，`restore` 一条命令 |
| 只增不减守卫 | 合并后行数或票数比旧数据少 → 拒绝写 | 0 | 直接不让它发生 |

快照为什么用硬链接：写入走"写 `.tmp` 再 `os.replace`"，替换只改目录项，
**旧 inode 的内容完好**，所以硬链接指向的仍是旧数据。只有当该分区真的被替换之后，
旧 inode 才由快照独占（一次日常 update 约 28 MB）。

**保留份数是 3，不是 10**（2026-11-10 改）。原因：快照粒度是「一次写事务」，
而补票是**按单票循环调 `add`** 的——一只票一份全库快照。10 份听起来不多，
实际是 10 × 全库旧版本 ≈ 3 GB；而第 10 份的回滚价值近乎零，因为增量写只增行，
退回去等于把后面 9 次合法新增扔掉。真正的需求是「刚写的这批坏了，退一步」，
3 份够用且便宜（稳态 ≈ 90 MB）。

⚠️ **`snapshots/` 的目录数会骗人，要看 `own_mb`。** 快照里没被替换过的分区
只是硬链接，删掉它们**一个字节都不释放**。2026-11-10 那次 87 份 / 表观 22 GB，
真实独占只有 2.4 GB，且 2.4 GB 全集中在 9 份里；另外 78 份与当前 `bars/`
是同一个 inode，`restore` 它们等于原地不动。先用 `snapshots` 命令看
「真实独占 X MB」，再决定删哪些。

实测：13 个分区全量快照后 `du -sh ~/MarketData` 仍是 **354 MB**
（bars 350 + meta/docs/analysis 4），再拍第二份 2026 也不变。
注意 `du -sh snapshots` 单看会显示 350 MB——那是**重复计数**：
硬链接与 `bars/` 共享 inode，`du` 只会把它算给先看到的那条路径。

```bash
python3 market_data.py snapshot --years 2026      # 手动留一份
python3 market_data.py snapshots                  # 现有快照
python3 market_data.py restore 20261108-120726-812-smoke           # 回滚（会自动先备份当前状态）
python3 market_data.py restore <stamp> --years 2014                # 只回滚某几年
```

`ingest` 默认 `protect=True`；`import_ss_cache` 显式关掉——源 json 还在，
而且一次迁移会触碰全部 13 个分区、连做几十批，逐批快照纯属浪费。

⚠️ **批量重写多个分区时，只在开头拍一次全库快照。** `rebuild_partition` 默认自己
也会拍，13 个分区连做会生成 13 份单分区快照，把「整轮回滚点」挤出保留窗口
（2026-11-08 修复权断点时踩到：开头那份全库快照 40 秒内就被自己挤掉了）。
批量调用方传 `protect=False`，由外层负责那一次快照。

⚠️ **清理必须真删。** 原实现是 `shutil.rmtree(d, ignore_errors=True)`，然后不管
删没删成都往 `gone` 里塞、日志照打「清理了 N 份」。在受限环境（后台任务 / 沙箱）
里 unlink 被拒时异常被吞，快照只增不减——2026-11-10 就是靠这个假成功积到
87 份 / 2.4 GB，全程零报错。现在删完强制 `os.path.exists` 复查，没消失就抛
`RuntimeError`，让调用方失败。`snapshot([])` 也改成了「显式空列表 = 什么都不拍」，
以前它走 falsy 分支会拍全库。

### 3.2 `check` 和 `verify` 的分工

| | 读什么 | 耗时 | 查什么 | 什么时候跑 |
|---|---|---|---|---|
| `check` | 只读 `code`/`date` 两列 | **0.9 秒**（全库） | 分区齐全 / 分区纯度 / 每票行数对账 | 每天 update 之后（`update.sh` 已接） |
| `verify` | 全库读进内存 | 约 30 秒 | 重复 / OHLC 关系 / 日期单调 / 对账 / 截面断层 | 周度、出事后、改完数据后 |

`check` 抓的两类问题都不会让 OHLC 检查变红：**行数悄悄变少**（历史被顶掉）和
**行落错分区**（2014 年里躺着 2026 的 bar，它和 2026 分区撞成重复，
还会在那只票序列尾造出 −99.8% 的假收益）。`check` 返回码非 0 表示不过。

---

## 4. 加票 / 换票

```bash
python3 ~/MarketData/market_data.py add 688981 300750   # 补全这两只的全部历史
python3 ~/MarketData/market_data.py add 600519 --start 2010-01-01
```

`add` 对已在库里的票会退化成增量。加完可以用 `status` 确认行数与最新日期。

### 批量补票（几百只以上）：必须分两阶段

`add` 是给手工补几只票设计的，批量场景下有两个坑：

1. **每票新建 MCP 会话 + `retries=3` + `timeout=240`**，一只 429 的票能把整批拖住
   十几分钟，而且看不出是哪只；
2. **一个批次全跑完才 `ingest`、才写一行进度**，1,500 只的黑箱，中途出事既不知
   进度也不知丢了什么。

所以用 `expand_run.py`，并且**拆成两个阶段**：

```bash
# 阶段 1：只拉数据到 pull_cache/（不碰 bars/，可以后台跑，慢）
python3 expand_run.py --stage pull --batch AC --workers 10 --chunk 100
# 阶段 2：一次性入库（替换 bars/*.parquet，必须在前台跑，快）
python3 expand_run.py --stage ingest
python3 expand_run.py --stage pull --retry-pending     # 二轮补失败票
```

为什么要拆：`ingest` 靠临时文件 + **原子替换**写 `bars/*.parquet`，这类操作在受管
环境里需要逐次审批。**后台任务拿不到审批**，会以
`PermissionError: Brokered host rename source refused by file policy` 失败——
而且报在 ingest 阶段，看着像数据源问题，实际一只都没入库。拉取阶段只新建
文件、不替换，后台跑没阻碍。

配套的 `expand_pool.py` 负责算出缺口清单（`pool_gap.json`），按「对当前检验口径
有没有用」分 A/B/C/D 四批，别一次全补——2015 年后上市的票在 `--list-years 3`
口径下根本进不了样本。

---

导出：

```bash
python3 ~/MarketData/market_data.py export --out /tmp/panel.csv --field close --start 2024-01-01
python3 ~/MarketData/market_data.py export --out /tmp/all.parquet --codes 600519 000001
```

---

### 4.1 全市场补票（千只以上）：走 HTTP 直连，别走 MCP

2026-11-14 补 panorama 宇宙的 2,095 只缺口时实测：同一个数据源，

| 通道 | 单票耗时 | 说明 |
|---|---|---|
| MCP `daily_hfq` | **284 秒** | 一次调用要过 MCP 封装 + JSON 序列化 |
| `GET /quotes/daily?return_format=csv` | **7~30 秒** | 直接吃同一个 pytdx batch，字段完全一致 |

脚本：`bulk_pull.py`（按缺口清单边拉边落盘，`pull_cache/done.txt` 记进度，可随时中断续跑）
＋ `backfill.sh`（循环「拉一批 → ingest → 再拉」，缺口清空后自动补元数据、重算体检、重建报告，
`mkdir` 锁防并发）。

```bash
python3 fetch_catalog.py                 # 拉全市场名录（含北交所），重算缺口 + 元数据补丁
python3 bulk_pull.py --workers 6         # 补票，写 pull_cache/
python3 expand_run.py --stage ingest     # 入库（前台）
python3 apply_meta_patch.py              # 补 board/list_date/status（ingest 不写这些）
./backfill.sh                            # 上面几步的无人值守循环版
```

三条口径，都是实测校对过的：

1. **`volume` 取 `volume_raw`（真实股数）**，不是 `volume_adj`。库内既有行、以及 MCP 通道
   补进来的 154 只，逐日核对（600519 / 001395）都是 raw。写错这一列，量能类因子整体差 factor 倍。
2. **北交所（920xxx）能补，但历史只从 2024-05-30 起**。920xxx 是 2024 年换号后的代码，
   更早的历史挂在旧的 83xxxx/87xxxx 下，接口按 920xxx 查不到。MCP 通道更是直接报
   「无法识别股票代码 920002 的交易所」——**只有 HTTP 通道能取北交所**。
3. **元数据别走 akshare**：`/api/v1/instruments` 一次给全市场 10,666 条的
   `listed_date / delisted_date / status / industry`，与日线同一个 `batch_id`，口径天然对得上，
   而且含北交所。`fill_meta.py`（akshare）仍可用于补申万分类。

**上游会长时间限流**。2026-11-14 实测吞吐在 3~10 只/分之间大幅波动，原因是行情服务自己
还挂着一个跑了 230 天没结束的 HKEX 回补任务（`/api/v1/data/download/progress` 可查），
我们的查询要排在它后面。补 2,000 只票是按小时计的活，**别指望一次跑完，靠 done.txt 续**。

### 4.2 日更与补票不能同时写：`.mdwrite.lock`

`update.sh`（21:00 主跑 + 23:30 兜底）和补票的 `expand_run.py --stage ingest` 是**同一类操作**：
读全库 meta → 合并 → 整体重写 `meta.json`。同时跑的后果不报错但很脏：

- 两边各持「开头读到的快照」，后写者把先写者**新增的票从 meta 里抹掉**。bars 还在，
  但 `md.codes()` 看不见 → 补票脚本以为没补过 → 无限重拉，缺口永远不归零。
- 写入前的 snapshot「只增不减」校验两边拿同一个基线算，会互相误判成数据丢失。

所以有了一把独立的写锁（`locklib.sh`），`.update.lock` / `.backfill.lock` 只管「自己别跑两份」，
`.mdwrite.lock` 管「谁在改库」：

| 角色 | 行为 |
|---|---|
| `update.sh` | 进锁最多等 900 秒（优先方）；等不到退出 3，21:00 / 23:30 两趟互为兜底 |
| 补票 ingest | 只等 120 秒；拿不到就**跳过本轮入库**，数据留在 `pull_cache`（入库幂等，下轮再灌） |
| 补票拉取 | 见 `.update.lock` 就暂停 60 秒；`bulk_pull.py` 每 20 只查一次，日更一起来就提前收尾并落盘 |
| panorama 日报 | 取 ASOF 前等 `.mdwrite.lock` 最多 25 分钟，超时 exit 4 拒绝出报告 |

最后一条是给**读者**的：分区是 `os.replace` 原子替换，读不到半个 parquet，但会读到
「一部分票有今日 bar、一部分还没有」的混合截面——动量/波动因子当场错位，而报告看起来一切正常。

配套的覆盖度闸门在 `panorama/check_freshness.py`：除了日期，还查当天有 bar 的票数占比
（2026-11-13 是 4,116/4,379 = 94%），<88% 告警、<60% 判 STALE 拒绝发布。

### 4.3 两个会让日更「空转两小时」的坑

1. **终点别用「今天」，用「最近交易日」**。`update` 默认 `end=今天`；2026-11-14 是周六，
   手跑一次，4,276 只票全被判成「待更新」，每只都去源端要周末 K 线、拿回 0 行，
   实测 2 秒/只 ≈ **2.4 小时纯空转**，还把同服务器的补票任务一起拖进 429。
   `update.sh` 现在先跑 `trading_day.py` 拿最近交易日再 `--end`：同样一轮变成
   「待更新 90 只，3 分钟收工」。注意服务端 `/api/v1/calendar/trading/previous`
   目前返回 500，只能用区间接口 `/api/v1/calendar/trading?exchange=SSE&start_date=&end_date=`。
2. **`pending_add.txt` 会被写脏**：行尾带 `# RuntimeError(...)` 注释。整行当代码塞进
   `python -c "... '001268  # RuntimeError...' in md.codes()"` 就是 `SyntaxError`，
   于是每一轮都显示「仍失败」，其实这 6 只**早就在库里**。清洗后 7 行只剩 1 只真失败。

---

## 5. 已知限制（重要，别当成全市场数据库）

1. **退市股只补进了 169 只，而且样本里只有一半**。2026-11-08 前库里只含"今天还活着"的票；
   现在补了 169 只 `status=delisted` 的退市股，但 `min_bars=400` 这类长度门槛会让
   2019 年前就退市的票落选。**幸存者偏差是缓解，不是消除**，做长期回测仍要意识到这一点。
2. **只有日线，没有分钟线 / 逐笔 / 财务 / 股本**。市值类因子需要另接数据。
3. **起始于 2014-06**，不是上市首日。更早的历史需要 `add --start` 单独补。
4. **后复权价的绝对值没有经济含义**，只能用于算收益率、比值与技术指标。
5. **停牌日没有 bar**（不是补 0），做面板时要注意 `NaN` 与"未上市"的区别。
6. **`tradestatus` 与涨跌停不是一回事**：ST 的 ±5%、双创的 ±20%、新股首周不设限，
   这些规则库里没有存，需要按代码/日期自己判断。
7. **分类信息是"当前"的**：`sw1/sw3` 取自申万现行分类，不是历史时点归属；
   `sw2` 全库仍为空（当前下游只用一级）。
8. **行情不许跨源拼**：本库是 `stock-server.daily_hfq` 口径。实测 `000001` 同 203 天
   与 akshare `stock_zh_a_hist(adjust="hfq")` 比值 1.206–1.261（非恒定），
   **逐日收益率最大差 0.94%**。akshare 只用来补元数据；要扩池请走 `market_data.py add`，
   别把别的源的日线直接并进 `bars/`。
9. **元数据曾整行缺失**：2026-11-07 前 515 只只有 K 线、没有 `board`/`list_date`/`sw1`。
   现已补齐到 100%（`fill_meta.py`，口径校验 1520/1520 一致，只填空不覆盖），
   每票带 `meta_source` 标记来源；原表备份为 `meta.json.bak-*`。
10. **`volume` 单位在库里不统一**：`ss_cache` 迁来的票是「股」，`stock-server daily_hfq`
    直接补的票（多为退市股）是「**手**」，相差 100 倍且不报错。2026-11-08 实测
    79/3,308 只属于后者。下游 `qdata.norm_volume_unit()` 会按
    `amount/(volume*100*close)` 的比值自动归一化（≈0.01 是股、≈1 是手），
    **直接读库自己算量能时要留意这一条**，别假设 volume 一定是股。
    **2026-11-14 补充（更麻烦的一层）**：口径不统一不只体现在票与票之间，同一只票的
    不同日期也会不一致。600519：2026-11-10 的 `volume` 是 `volume_adj`（300,309），
    11-11~11-13 是 `volume_raw`（3,984,700 等），差 7.67 倍——复权因子那么大，
    肉眼看数字完全看不出异常。判据只能是逐行算 `amount/(volume*close)`：
    等于 `1/factor` 是 raw、等于 1 是 adj。`bulk_pull.py` 取 `volume_raw`。
11. **退市股的 `sw1` 只有 95%**：申万成分表只含现存标的，170 只退市股拿不到行业分类，
    行业中性化时它们会被略过（`ind_static` 97.4%，仍高于 90% 的可用门槛）。
12. **补票会掉**：2026-11-08 那轮 A+C 批 1,542 只，实际入库 1,449 只，93 只卡在上游
    429 限流。`pending_add.txt` 留着清单，`expand_run.py --stage pull --retry-pending`
    可续补；补完 `n_stocks` 会变，判定必须重算。
13. **分区曾经被增量写整块顶掉（已修）**：2026-11-08 09:18 一次 `add` 让
    `bars/2014.parquet` 只剩本批 1,429 只新票，原库 968 只票的
    2014-06-03~2014-12-31（**138,975 根**）静默消失。原因是分区文件在写入那一刻
    不存在时，代码走"新建分区"分支，把一批增量当成整年数据写回去——
    `os.replace` 是原子替换，旧行没有第二份。当日已用 `repair_2014.py`
    定向补回（缓存 138,976 行 / 968 只，日期窗口 2014-06-03~2014-12-31），
    全库 **9,112,526 根**、`verify` 重复 0 / OHLC 异常 0 / 对账 0。
    现在三道防线：① 合并结果不得比旧数据少（丢行/丢票都中止）；
    ② 元信息声明的库区间内，每一年都必须有分区文件；③ 写前硬链接快照 +
    写后指纹比对（见 §3.1）。要缩减分区只能显式 `rebuild_partition()`。
    **教训**：`doctor` 当时 11 项全过，因为所有检查都在问
    "池子里有什么"，没有一项在问"库里声称的和磁盘上真有的对得上吗"；
    现在 `doctor` 多了一条「库对账」，库自己多了一条 `check`。
14. **快照只保护"写路径"**：`snapshot` 挂在 `ingest` 上，只覆盖本库自己的写。
    如果你手动 `rm`/另写脚本动 `bars/`，快照救不了——那种情况只能靠
    每天 `update.sh` 里的 `check` 事后发现，或者自己先 `snapshot`。
    另外 `snapshots/` 保留最近 3 份，第 4 次写入会删掉最旧那份；
    做危险操作前先手动 `snapshot --tag 动手前`。

---

## 6. 维护

| 场景 | 做法 |
|---|---|
| 忘了更新，数据旧了 | `python3 market_data.py update`；`status` 会在超过 5 天时提示 |
| 怀疑数据变少 / 落错分区 | `python3 market_data.py check`（0.9 秒）；不过再跑 `verify` |
| 怀疑某个分区损坏 | `python3 market_data.py verify --deep`，看重复/OHLC/对账三项 |
| 写坏了想退回 | `python3 market_data.py snapshots` 挑一份 → `restore <stamp>` |
| meta 与数据对不上 | `python3 market_data.py rebuild-meta`（从 parquet 反推，保留名称与行业） |
| 想从别处迁移旧缓存 | `python3 market_data.py import <含 *.json 的目录>`（json 需含 `code` 与 `bars`） |
| 从交易所名单批量补票 | `python3 expand_pool.py` 出缺口清单 → `expand_run.py --stage pull` → `--stage ingest`（见 §4） |
| 改库位置 | 设环境变量 `MARKET_DATA_HOME=/path/to/dir` |
| 换数据源地址 | 设环境变量 `STOCK_SERVER_URL=http://host:port/mcp` |
| 某个分区被顶掉 | `python3 repair_2014.py --stage pull` → `--stage ingest`（改窗口即可复用） |
| 更新被限流 / 中途收工 | 失败的票已写进 `pending_update.txt`，下次 `update` 自动排最前；退出码 2 表示中途收工 |
| 发现单日暴跌暴涨但当天没成交 | `python3 fix_adjbreaks.py` 先看报告；确认是断点再加 `--apply`（见 §2 的零成交说明） |

自检：`python3 ~/MarketData/test_market_data.py`（45 条，不联网，用临时目录）。
数据口径与已知瑕疵清单：`docs/00-数据字典.md`。

### 调度与限流

交易日 **21:00** 由 launchd 调 `update.sh`（周一至周五，`~/Library/LaunchAgents/com.wfeixu.marketdata-update.plist`）。
23:30 的 WorkBuddy automation 保留为**兜底体检**：21:00 那轮跑完它只花几秒确认 0 只待更新；
21:00 那轮若失败/没跑成，它接手补跑。两者靠 `.update.lock` 互斥，不会并发写同一分区。

为什么不更早：库的增量是**单向**的（`start = meta.last + 1`），已写入的 bar 不会被后续
update 修正。早跑若拿到还没定稿的成交额/复权因子，错值会永久固化。历史窗口是 23:30，但库长到
3300+ 只后单轮要 100 分钟，23:30 起跑必然跨到次日凌晨一点多，与调度重叠、也容易被会话结束
打断——2026-11-10 那晚就是这么丢掉一整天的（跑到 2600/3329 被杀，未落盘）。前移到 21:00
能保证当晚收工。距收盘 6 小时是否够，2026-11-11 的实测给了答案：**不够也不差**。
那天 11-10 的 bar 是次日 08:10 抓的（收盘后 17 小时），源端对 `603596` 仍返回除权前的旧因子，
说明因子滞后是**按天**而不是按小时，21:00 与 23:30 没有区别。真要防这一类，靠的不是晚跑，
是 `update` 输出的「新旧衔接跳空 >25%」告警 + `analysis/scan_bad_bars.py` 用官方涨跌幅仲裁
（详见 `docs/00-数据字典.md` 瑕疵 4c）。

**并发锁**：`update.sh` 起手 `mkdir .update.lock`，抢不到且 pid 还活着就直接退出（退出码 0），
pid 已死则视为残留锁自动接管。2026-11-09 出过两个 update 同时写同一 parquet 互相覆盖的事故，
这道锁是补那个洞。

**它曾经的失败方式**（2026-11-02~05 连续四晚）：`sorted(st)` 从 000001 往后请求，
跑到 0005xx 撞 429 限流 → 连续 18 只失败 → 判定"源端故障"收工 → 退出码 0。
每晚只跑 47/1524 只，日志一片绿，238 只票的 `last` 一路停在 10-30。现在：

- **全局节流闸门**：所有线程共用一个发送间隔（基准 0.2 秒 ≈ 5 请求/秒），撞 429 就
  翻倍（上限 2 秒）并重新排队，成功一次往回收一点。不再各线程各自退避后同时重发。
- **429 不算源端故障**：只有连续 18 只*非限流*失败才熔断；限流要先重试 6 次
  （约 8 秒退避），连续 18 只仍被拒才判定当晚配额用尽。
- **失败清单落盘**：`pending_update.txt`（`code` + 已到哪一天），下次优先跑，
  不再每天从 000001 重排、在同一段再撞一次。
- **退出码不再吞**：中途收工 `exit 2`，定时任务能看见。

### 备份

整个 `~/MarketData/` 就是全部（`bars/` 349 MB + `snapshots/` 304 MB）。拷走即可，无外部依赖：

```bash
tar -czf ~/MarketData-$(date +%Y%m%d).tar.gz -C ~ MarketData
```

只想要数据本身、不要快照：`--exclude='MarketData/snapshots'`，约 349 MB。
`snapshots/` 里的文件是硬链接，`tar` 会**展开成实体文件**，打包体积按全量算。

---

## 7. 从哪来的

首批 1,521 只来自 2026-11-01 的因子研究扩样本（`factor_lab` 的 `data/ss_cache`，1,525 个 JSON），
迁移后逐值比对抽样 8 只 **0 处差异**。后续扩到 2,036 只时只补了行情、没补元信息，
于是留下 515 只元数据整行为空的票——2026-11-07 用 `fill_meta.py` 补齐。

**2026-11-08 扩池**：按「早于 2015 上市 / 2015 后上市 / 区间内退市 / 库起点前退市」四批补齐，
2,037 → 3,486 只（含 169 只退市股），并把上市日与退市标记一起写进 meta。
口径默认化与批次明细见 `docs/数据层-口径默认化与扩池说明.md`。

**还没做的**：

- B 批 1,902 只（2015 年后上市）未补，需把 `start` 后移才能取到，代价是历史窗口变浅；
- 退市股覆盖仅 169 只，外部分析口径约 284 只 —— **幸存者偏差只减轻，没消除**；
- 170 只退市股缺 `sw1`（申万成分表只含现存标的），行业中性化时被略过。

---

## 8. 文件地图（每样东西放哪、为什么）

| 路径 | 是什么 | 谁在用 |
|---|---|---|
| `market_data.py` | 库本体，所有读写与 CLI | 所有分析脚本、`update.sh` |
| `bars/` | 数据本体，13 个年分区 | 只读 |
| `snapshots/` | 写前硬链接快照，留最近 3 份 | 出事时 `restore` |
| `backup/meta-*.json` | meta 的定版副本（`bars` 有快照，`meta` 靠它） | 手工回滚 |
| `docs/00-数据字典.md` | **字段口径、单位、陷阱、常用查法** | 写任何分析前先读 |
| `docs/数据层-*.md` | 四次数据层事故/变更的完整复盘 | 想知道「为什么这么设计」 |
| `docs/adjbreak_fixed_*.csv` | 被修掉的复权断点逐行清单（原值/修正值/假收益） | 核对修复、手工回退 |
| `fix_adjbreaks.py` | 零成交日的复权断点检查（默认只报告） | 每季，或见到「没成交却大涨」时 |
| `analysis/*.py` | 读库出结论的分析脚本（可重跑） | 复用方法，别重写 |
| `analysis/out/*.csv` | 上面脚本产出的结果表 | 报告引用、交叉核对 |
| `logs/update-*.log` | 每日增量的完整输出 | 查「那晚到底跑了什么」 |
| `updates.jsonl` | 结构化审计：每次写入的标的数/新增行/失败清单/快照名 | 追责与对账 |
| `pool_*.json`、`expand_progress.json` | 扩池用的外部来源缓存与进度 | `expand_pool.py` / `expand_run.py` |
| `pending_*.txt` | 取数失败的票，下次优先重试 | `update.sh` |

判断标准很简单：**「下次还会用到」→ 留在这里并写进本表；「只服务那一次」→ 进 `docs/` 当记录；
「可再算出来」→ 不存。**
