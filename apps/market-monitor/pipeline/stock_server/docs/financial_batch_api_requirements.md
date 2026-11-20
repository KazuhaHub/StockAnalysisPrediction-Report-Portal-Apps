# stock_server 财务数据批量接口需求

## 1. 背景与目标

quantwin 是一个全 A 股月度调仓的多因子选股程序，历史回溯从 2012-01-01 起，每期需要对**全体股票**做横截面打分。目前财务数据依赖 AKShare 的两个全市场接口：

- `stock_yjbb_em`（业绩报表，按报告期返回全市场）
- `stock_yysj_em`（业绩披露时间，按报告期返回全市场）

这两个接口由东方财富网页端抓取，长期存在限流、字段变更、字段口径漂移等问题，已经影响取数稳定性。当前 stock_server 已有的单股财务接口（`/research/company/{instrument_id}/financial-statements/history`）字段完整，但实测 **78–101 秒/只**，全市场 5300 只无法使用。

**目标**：stock_server 提供一个“按报告期返回全市场财务指标”的批量接口，使 quantwin 能完全替代 AKShare 的财务取数，并保证**时点正确（point-in-time，无未来函数）**。

---

## 2. P0 需求：财务指标批量接口

### 2.1 接口定义

```
GET /api/v1/research/financials/batch
```

### 2.2 请求参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `report_period` | string | 是 | — | 报告期，格式 `YYYYMMDD`，仅允许 `0331 / 0630 / 0930 / 1231` 四个值 |
| `as_of` | string(date) | 否 | null | 时点过滤：只返回 `publish_date <= as_of` 的记录；为空则返回该报告期全部记录 |
| `include_delisted` | bool | 否 | `true` | 是否包含已退市股票（量化回测必须包含，否则存在存活偏差） |
| `exchanges` | string | 否 | 全部 | 逗号分隔：`SSE,SZSE,BSE`；默认沪深北全部 |
| `limit` | int | 否 | 1000 | 单页最大 2000 |
| `offset` | int | 否 | 0 | 分页偏移 |

### 2.3 响应结构

```json
{
  "report_period": "20260930",
  "as_of": null,
  "total": 5342,
  "limit": 1000,
  "offset": 0,
  "items": [
    {
      "instrument_id": "600519.SH",
      "symbol": "600519",
      "name": "贵州茅台",
      "exchange": "SSE",
      "report_period": "20260930",
      "publish_date": "2026-10-29",
      "currency": "CNY",
      "eps": 50.12,
      "bps": 250.3,
      "ocfps": 48.7,
      "roe": 21.5,
      "gross_margin": 91.2,
      "rev_yoy": 12.4,
      "np_yoy": 15.1,
      "revenue": 130000000000.0,
      "net_income": 63000000000.0,
      "operating_cf": 61000000000.0,
      "equity": 320000000000.0,
      "total_assets": 780000000000.0,
      "shares_outstanding": 1256197800,
      "industry": "白酒",
      "is_delisted": false,
      "updated_at": "2026-10-30T08:00:00+08:00"
    }
  ]
}
```

### 2.4 字段口径（务必逐条确认）

| 字段 | 类型 | 单位 | 口径与约束 |
|---|---|---|---|
| `instrument_id` | string | — | 与 `/quotes/daily` 一致，如 `600519.SH`；退市股票也必须可被行情接口查询 |
| `report_period` | string | — | 回显请求的报告期，`YYYYMMDD` |
| `publish_date` | string(date) | — | **实际公告日**（巨潮/交易所披露日），不是报表所属期。缺失时返回 `null`，**不要**用法定截止日或报告期末日顶替 |
| `eps` | number | 元 | 累计（年初至报告期末）基本每股收益，**不要预先年化**；由客户端按报告期折算 |
| `bps` | number | 元 | 每股净资产 |
| `ocfps` | number | 元 | 每股经营活动现金流量净额（累计）；若难以直接提供，可只给 `operating_cf` + `shares_outstanding`，由客户端换算 |
| `roe` | number | % | 净资产收益率，累计值（如 `21.5` 表示 21.5%） |
| `gross_margin` | number | % | 销售毛利率 |
| `rev_yoy` | number | % | 营业总收入同比增长率；**需服务端计算**（本期营业收入 vs 上年同期） |
| `np_yoy` | number | % | 归母净利润同比增长率；**需服务端计算** |
| `revenue` / `net_income` / `operating_cf` / `equity` / `total_assets` | number | 元 | 原始报表值，便于客户端做 TTM、校验与自定义因子 |
| `shares_outstanding` | number | 股 | 报告期末总股本，用于每股类指标换算与 EPS 校验 |
| `industry` | string | — | 行业分类（建议与 `/instruments` 的 industry 同源同口径），随最新年报更新 |
| `is_delisted` | bool | — | 该报告期后是否已退市 |
| `updated_at` | string(datetime) | — | 记录在服务端的最后更新时间（便于客户端判断追溯调整） |

**数值型字段统一规则**：使用 JSON number；缺失返回 `null`，**禁止**返回 `0`、`""`、`"-"`、`"0.00%"` 等占位值（`0` 会被当作真实财务值参与截面排序，直接污染因子）。

### 2.5 覆盖与回溯要求

- 报告期范围：`20120331` 起至最新已披露报告期，共约 56 期
- 每期覆盖全市场（含当期已退市股票），2026Q3 起每期应 ≥ 5300 只
- 支持北交所（`BSE`），可被 `exchanges` 参数开关
- 最近 8 个季度允许重复拉取，返回追溯调整后的最新口径（同一报告期数值可变，`updated_at` 随之更新）

### 2.6 性能要求

- 单页 1000 行响应时间 ≤ 3 秒（冷启动首次查询 ≤ 30 秒）
- 全量 56 期（约 30 万行）顺序拉取总耗时 ≤ 10 分钟（每期 6 页）
- 建议服务端预计算并落库，避免每次请求实时聚合

---

## 3. P1 需求：全市场单日行情批量接口（性能增强）

现状：`/quotes/daily` 只支持单只 `instrument_id`，quantwin 每日增量需 5300 次请求（约 1.5–2 小时）。

```
GET /api/v1/quotes/daily/bulk
    ?trade_date=2026-10-30
    &adjust=hfq
    &include_delisted=true
    &limit=2000&offset=0
```

字段与 `/quotes/daily` 完全一致（`instrument_id, time, open, high, low, close, volume, amount, turnover, tradestatus, adjustment_factor`）。补充两点：

- `turnover`（换手率 %）在最近交易日实测返回 `0`，请修复为真实换手率，或明确说明该字段不可用
- 若无法提供 `turnover`，请在 P2 的估值批量接口中提供 `float_market_cap`，客户端可用 `成交额/流通市值` 近似换手率

---

## 4. P2 需求（可选，有了更好）

1. **估值批量**：`GET /api/v1/research/valuations/bulk?trade_date=&include_delisted=true`
   返回 `instrument_id, pe_ttm, pb_mrq, ps_ttm, total_market_cap, float_market_cap`，用于 `size` 因子与估值类因子，避免客户端用成交量/换手率反推流通股本。
2. **行业分类批量**：`GET /api/v1/industries?level=1` 返回行业代码、名称、层级，便于统一分类口径。
3. **数据完整性自检**：`GET /api/v1/research/financials/coverage?report_period=` 返回该期应有/实际股票数、缺失数、`publish_date` 为空数量，方便客户端监控。

---

## 5. 验收标准

开发商交付前请逐项自测，quantwin 会按以下规则验收：

| # | 验收项 | 通过标准 |
|---|---|---|
| 1 | 字段对比 | 随机抽 20 只 × 3 个报告期，`eps/bps/roe/gross_margin` 与巨潮资讯/东财公开数据相对误差 ≤ 1%（追溯调整允许误差） |
| 2 | 披露日正确性 | 抽 50 条，`publish_date` 与公告日一致；`as_of=t` 查询时不得出现 `publish_date > t` 的记录 |
| 3 | 缺失值语义 | 抽查无数据场景，字段必须是 `null`；全响应中 `0` 不能作为缺失占位 |
| 4 | 覆盖率 | 2026Q3 期返回股票数 ≥ 5300（含退市）；2012Q1 期 ≥ 2300 |
| 5 | 同比字段 | `rev_yoy / np_yoy` 与上年同期原始值手工计算误差 ≤ 0.1 个百分点 |
| 6 | 幂等性 | 同一参数连续两次请求，除 `updated_at` 外结果一致 |
| 7 | 分页完整性 | 分页遍历后 `total` 与实际条数一致，无重复、无遗漏 |
| 8 | 性能 | 单页 ≤ 3 秒；56 期全量 ≤ 10 分钟 |
| 9 | 兼容性 | `instrument_id` 可直接用于 `/quotes/daily`；退市股票行情可查 |

---

## 6. 错误码约定

| 状态码 | 场景 | 响应体 |
|---|---|---|
| 400 | `report_period` 非法（非四个季末日期） | `{"detail": "invalid report_period, expect 0331/0630/0930/1231"}` |
| 404 | 该报告期尚无任何披露数据 | `{"detail": "no data for report_period 20261231"}` |
| 429 | 触发限流 | 带 `Retry-After` 头 |
| 500 | 服务端内部错误 | 通用错误体，禁止返回 HTML |

接口需保持与现有 `/api/v1/quotes/daily` 一致的鉴权与限流策略，并在 `openapi.json` 中补齐 schema。

---

## 7. 交付与联调

1. 提供 `openapi.json` 更新（含 4xx 响应 schema）
2. 提供一个可直接跑的 `curl` 示例（含分页遍历示例）
3. 上线后提供 1 周灰度地址，quantwin 会跑“akshare 与 stock_server 双取数对比”，逐字段核对差异后再切换
4. 若某字段短期内无法提供，请在响应中返回 `null` 并在交付说明中标注，不要返回近似值
