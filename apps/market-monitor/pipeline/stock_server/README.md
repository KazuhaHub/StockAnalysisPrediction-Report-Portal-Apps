# Stock MCP Server

基于 FastMCP 的股票数据 MCP (Model Context Protocol) 服务，提供股票行情数据查询和技术分析功能。

## 功能特性

### 可用接口说明
http://47.237.204.217:8000/openapi.json

### 📊 股票数据查询
- **日度行情数据** - 获取指定日期范围的股票日线数据（开盘价、收盘价、最高价、最低价、成交量等）
- **最新行情数据** - 获取单只或多只股票的最新实时行情
- **交易日历查询** - 查询上海证券交易所（SSE）和深圳证券交易所（SZSE）的交易日历
- **上/下一交易日** - 本地计算指定日期的上一个/下一个交易日
- **股票基本信息** - 查询股票的基本信息（股票名称、交易所、上市日期等）
- **交易品种查询** - 按交易所、行业等维度筛选交易品种

### 📈 技术分析指标（本地计算）
- **移动平均线 (MA)** - 支持 20日、50日、200日等多种周期
- **MACD 指标** - 包含 DIF、DEA、MACD 柱状图
- **RSI 指标** - 相对强弱指数，默认 14 日周期
- **布林带 (Bollinger Bands)** - 默认 20 日周期，2 倍标准差
- **KDJ 指标** - 随机指标，默认参数 (9, 3, 3)
- **ATR 指标** - 真实波动幅度，默认 14 日周期

### 🔬 公司研究数据（服务端）
- **行业归属** - 申万行业分类，含一/二/三级行业
- **财务报表** - 资产负债表、利润表、现金流量表
- **相对估值** - 与同行业公司的估值对比
- **DCF估值** - 贴现现金流估值，支持自定义参数
- **技术分析摘要** - 服务端计算的趋势、动量、波动综合评估
- **技术指标数据** - 服务端计算的 MACD、RSI、KDJ 等指标

### 📉 风险分析（本地计算）
- **回归Beta** - 个股对基准指数的Beta系数，含Alpha、R²、相关性

### 🏭 行业研究数据（服务端）
- **行业分类体系** - 申万行业分类查询
- **行业成分股** - 查询行业下包含的股票
- **行业指数分析** - 行业指数行情和指标数据

### 🚀 技术特性
- **双传输模式** - 支持 stdio（本地IDE）、SSE 和 Streamable HTTP（服务器部署）三种模式
- **FastMCP 框架** - 基于 FastMCP 3.x，性能优异
- **自动交易所识别** - 根据股票代码自动识别所属交易所
- **智能数据预处理** - 自动调整数据范围以计算技术指标
- **统一输入验证** - stock_code、日期、instrument_id 格式校验
- **统一异常处理** - MCP工具层捕获所有异常，防止工具崩溃
- **请求重试机制** - 网络瞬断自动重试（最多3次）

## 系统要求

- Python 3.9 或更高版本
- Windows / Linux / macOS

## 安装

### 方式一：使用启动脚本（推荐）

**Windows:**
```bash
start_server.bat
```

**Linux/macOS:**
```bash
chmod +x start_server.sh
./start_server.sh          # 默认Streamable HTTP模式，端口8091
./start_server.sh http     # Streamable HTTP模式（推荐）
./start_server.sh sse      # SSE模式，端口8091
./start_server.sh stdio    # stdio模式
```

### 方式二：手动安装

1. 创建虚拟环境（可选）
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 启动服务
```bash
# stdio模式（本地IDE使用）
python stock_mcp_integrated.py

# Streamable HTTP模式（推荐，服务器部署）
MCP_TRANSPORT=http python stock_mcp_integrated.py

# SSE模式（服务器部署）
MCP_TRANSPORT=sse python stock_mcp_integrated.py

# 自定义端口
MCP_TRANSPORT=http MCP_PORT=8091 python stock_mcp_integrated.py
```

## 运行模式

### stdio 模式（本地IDE集成）

通过标准输入输出通信，适合本地IDE（如 Trae、Claude Desktop）使用。

```bash
python stock_mcp_integrated.py
```

### SSE 模式（服务器部署）

通过 HTTP SSE 协议通信，适合部署到服务器供远程访问。

```bash
# 默认端口 8091
MCP_TRANSPORT=sse python stock_mcp_integrated.py

# 自定义端口和地址
MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8091 python stock_mcp_integrated.py
```

SSE端点地址：`http://<服务器IP>:8091/sse`

### Streamable HTTP 模式（推荐，MCP协议新标准）

MCP 协议的新标准传输方式，性能优于 SSE，推荐服务器部署使用。

```bash
# 默认端口 8091
MCP_TRANSPORT=http python stock_mcp_integrated.py

# 自定义端口和地址
MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8091 python stock_mcp_integrated.py
```

Streamable HTTP端点地址：`http://<服务器IP>:8091/mcp`

### 环境变量

| 环境变量 | 说明 | 默认值 |
|---------|------|-------|
| `MCP_TRANSPORT` | 传输模式：`stdio`、`sse`、`http` | `stdio` |
| `MCP_HOST` | HTTP/SSE监听地址 | `0.0.0.0` |
| `MCP_PORT` | HTTP/SSE监听端口 | `8091` |
| `MCP_SESSION_IDLE_TIMEOUT` | Streamable HTTP 会话空闲回收秒数；设为 `0` 或负数则关闭回收 | `1800`（30 分钟） |

> `MCP_SESSION_IDLE_TIMEOUT` 只对 `http`（streamable-http）模式生效。会话在超过该时长没有任何 HTTP 请求时会被自动终止并释放，日志中会逐条出现 `Session xxx idle timeout`。若客户端只做请求-响应、长期不发 `DELETE`，建议保持默认值以避免会话堆积。

## 在 MCP 客户端中配置

### stdio 模式配置（本地IDE）

```json
{
  "mcpServers": {
    "stock-server": {
      "command": "python",
      "args": ["/path/to/stock_mcp_integrated.py"]
    }
  }
}
```

### SSE 模式配置（远程连接）

```json
{
  "mcpServers": {
    "stock-server": {
      "url": "http://<服务器IP>:8091/sse"
    }
  }
}
```

### Streamable HTTP 模式配置（远程连接，推荐）

```json
{
  "mcpServers": {
    "stock-server": {
      "url": "http://<服务器IP>:8091/mcp"
    }
  }
}
```

## 可用工具列表

> **v3.3 口径治理**：在 v3.2 基础上新增行情复权口径派生、财务响应裁剪、数据健康自检，并启用 Streamable HTTP 会话空闲回收。当前对外暴露工具数为14（新增 `query_data_health`）。v3.0 将39个原子工具聚合为9个领域工具，v3.1 新增商品/外汇/无风险利率3个，v3.2 新增财务 PIT 面板。

### 工具总览

| 工具名称 | 描述 | action 列表 |
|---------|------|------------|
| `query_stock_quote` | 股票行情 | `latest`, `daily` |
| `query_stock_fundamental` | 股票基本面 | `financial`, `financial_history`, `shareholders`, `industry` |
| `query_stock_valuation` | 股票估值 | `relative`, `dcf`, `history`, `percentile` |
| `query_stock_beta` | Beta系数 | `server`, `regression` |
| `query_stock_technical` | 技术分析 | `summary`, `indicators`, `full`, `ma`, `macd`, `kdj` |
| `query_trading_calendar` | 交易日历/品种 | `calendar`, `next_day`, `previous_day`, `instrument`, `stock_info` |
| `query_industry_data` | 行业研究 | `taxonomy`, `components`, `index_analysis`, `as_of`, `company_as_of` |
| `query_futures_basic` | 期货基础 | `instruments`, `instrument_detail`, `contracts`, `calendar`, `readiness`, `dictionary` |
| `query_futures_series` | 期货序列 | `series`, `series_prices`, `series_mapping`, `cycle_diagnostics`, `default_prices`, `contract_prices` |
| `query_commodity_data` | 商品数据 | `series`, `observations`, `dictionary`, `diagnostics`, `indicators`, `policy_events` |
| `query_fx_data` | 外汇数据 | `series`, `rates`, `convert`, `indices`, `index_observations`, `dictionary`, `readiness` |
| `query_risk_free_rate` | 无风险利率 | `series`, `rate` |
| `query_financial_pit` | 财务PIT面板 | `cross_section`, `panel`, `coverage`, `changes` |
| `query_data_health` | 数据健康自检 | -（单次调用返回全部数据集状态） |

### 1. query_stock_quote - 股票行情

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `latest` | 最新行情 | `stock_code` 或 `instrument_id` | - |
| `daily` | 日K线 | `stock_code`/`instrument_id`, `start_date`, `end_date` | `adjust`: 复权类型；`include_suspended`、`min_quality_score`、`is_complete`、`min_volume`: 过滤参数 |

> `stock_code` 支持逗号分隔的多个代码，如 `"600519,000001"`
>
> **停牌日过滤**：停牌日不会缺行，而是以「零成交量行」存在（`volume=0`、OHLC 全等前收、`tradestatus=0`、`is_complete=false`、`quality_score=0.4`）。实测 000002.SZ / 2016-06-01~07-31 共 41 行，其中 21 行是停牌日。做横截面或量价筛选时请传 `is_complete=true` 或 `min_volume=1`（实测均只返回 20 行）。
>
> 注意：`include_suspended` 与 `min_quality_score` 后端接受但不做过滤（实测传 false / 0.9 仍返回 41 行），已列入后端需求清单 B-09；当前请用 `is_complete` / `min_volume` 达到同样效果。

#### 口径契约（必读）

后端在 `adjust=hfq` 时，同一行内混用三套口径：`open/high/low/close/volume` 为后复权，`pre_close/change` 为未复权，`amount` 为真实元。直接 `close/pre_close-1` 会得到数量级错误的结果。

MCP 层不改原始字段，只在 `factor != 1` 时为每行追加 `derived` 块（实测 600519 / 2026-11-06：`close_raw=1452.9999`、`volume_raw=4284698`、`avg_price_raw=1446.90`）：

| 派生字段 | 计算方式 | 用途 |
|---------|---------|------|
| `close_raw` / `open_raw` / `high_raw` / `low_raw` | 原值 ÷ factor | 真实价格 |
| `pre_close_adj` | `pre_close × factor` | 与复权价同口径 |
| `volume_raw` | `volume × factor` | 真实股数 |
| `avg_price_raw` | `amount ÷ volume_raw` | 真实成交均价 |
| `pct_change_decimal` | `pct_change ÷ 100` | 无量纲比例，可跨接口比较 |

> `pct_change` 为**百分数**（0.0689 表示 0.0689%），响应顶层 `units` 显式声明；`query_stock_technical` 的 `pct_change_1d` 为**小数**，两者相差 100 倍，跨接口比较请用 `derived.pct_change_decimal`。
>
> `latest` 返回顶层 `freshness`：`quote_type=snapshot`、`as_of`、`staleness_trading_days`、`is_same_trading_day`。`time` 字段只到交易日、不含时辰，**这不是交易所逐笔实时行情**。

### 2. query_stock_fundamental - 股票基本面

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `financial` | 财务报表（默认摘要，约2-5KB） | `stock_code`/`instrument_id` | `report_period`, `include_statements`, `fields`, `summary_only` |
| `financial_history` | 多报告期财务历史 | `stock_code`/`instrument_id` | `period_window`(默认latest), `rolling_quarters`(默认12), `include_statements`, `fields` |
| `shareholders` | 股东信息 | `stock_code`/`instrument_id` | `include_snapshot` |
| `industry` | 行业归属 | `stock_code`/`instrument_id` | `include_snapshot` |

> **P1-1 响应裁剪**：`financial` 完整响应约 190–280KB，会超出调用方单次返回上限。现默认 `summary_only=true`，只返回顶层科目 + `indicators` 概览（实测 2.3KB，数值逐字段一致）；`fields="revenue,net_income,roe"` 可进一步投影到 1.4KB；需要 `facts` / `indicators.details` 明细时传 `summary_only=false`。裁剪响应带 `_meta.omitted` 说明省略内容，不会静默丢数据。
>
> **注意**：`include_snapshot` 只对 `shareholders` / `industry` 生效；后端 `financial-statements` 接口没有该参数，传了不会改变返回体积。
>
> **单位差异**：`indicators` 中利润率/ROE 为**小数**（0.8976 = 89.76%），而 `query_financial_pit` 的 `cross_section` 同名字段为**百分数**（89.76 = 89.76%），跨接口拼接前必须换算。

### 3. query_stock_valuation - 股票估值

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `relative` | 相对估值 | `stock_code`/`instrument_id` | - |
| `dcf` | DCF估值 | `stock_code`/`instrument_id` | - |
| `history` | 估值历史 | `stock_code`/`instrument_id` | `start_date`, `end_date`, `limit`(默认120) |
| `percentile` | 估值分位数 | `stock_code`/`instrument_id` | `quarters`(默认12) |

### 4. query_stock_beta - Beta系数

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `server` | 服务端Beta（多窗口） | `stock_code`/`instrument_id` | `benchmark_family`, `window_days` |
| `regression` | 本地回归Beta | `stock_code`, `start_date`, `end_date` | `benchmark_code`(默认000300), `period`(默认60) |

### 5. query_stock_technical - 技术分析

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `summary` | 服务端技术摘要 | `stock_code`/`instrument_id` | `adjust` |
| `indicators` | 服务端技术指标 | `stock_code`/`instrument_id` | `adjust`, `limit` |
| `full` | 本地完整技术分析 | `stock_code`, `start_date`, `end_date` | - |
| `ma` | 本地MA分析 | `stock_code`, `start_date`, `end_date` | - |
| `macd` | 本地MACD分析 | `stock_code`, `start_date`, `end_date` | - |
| `kdj` | 本地KDJ分析 | `stock_code`, `start_date`, `end_date` | - |

### 6. query_trading_calendar - 交易日历/品种

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `calendar` | 交易日历 | `start_date`, `end_date` | `exchange`(默认SSE) |
| `next_day` | 下一交易日 | `date` | `exchange` |
| `previous_day` | 上一交易日 | `date` | `exchange` |
| `instrument` | 品种信息 | `stock_code`/`instrument_id` | - |
| `stock_info` | 股票基本信息 | `stock_code` | - |

### 7. query_industry_data - 行业研究

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `taxonomy` | 行业分类体系 | - | `taxonomy_system`(默认sw2021), `industry_level` |
| `components` | 行业成分股 | `sw_index_code` | - |
| `index_analysis` | 行业指数分析 | `sw_index_code` | - |
| `as_of` | 批量时点行业分类 | `as_of_date` | `as_of_taxonomy_system`(常用`sw`), `exchange`, `limit`, `offset` |
| `company_as_of` | 单票时点行业归属 | `stock_code`/`instrument_id`, `as_of_date` | `as_of_taxonomy_system`(常用`sw`), `include_snapshot` |

> **时点语义**：两个 `as_of` 动作都返回**历史时点**生效的行业分类，**当日无生效分类的股票不返回**（不回填最新分类）。做行业中性化须严格按返回结果关联，否则会引入未来函数。
>
> **两个易踩的坑**：
> 1. `as_of_taxonomy_system` 与 `taxonomy` 动作的 `taxonomy_system` 是两套取值——前者须用 `sw`（传 `sw2021` 会返回空集）。
> 2. 后端两个接口日期格式相反：批量 `/industries/as-of` 要 `YYYYMMDD`，单票 `/company/{id}/industry/as-of` 要 `YYYY-MM-DD`（传 `20260801` 会 422）。**本工具已自动适配**，调用方传 `20260801`、`2026-08-01`、`2026/08/01` 均可。
>
> **字段名差异**：单票返回 `official_industry_code`，批量返回 `industry_code`；单票生效区间为 `effective_date`/`expiry_date`，批量为 `effective_from`/`effective_to`。

### 8. query_futures_basic - 期货基础

> 期货 instrument_id 格式：`CNF.{品种}.{交易所}`，如 `CNF.AG.SHFE`。交易所：SHFE/DCE/CZCE/INE/GFEX。

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `instruments` | 品种列表 | - | `active_only`(默认True) |
| `instrument_detail` | 品种详情 | `instrument_id` | - |
| `contracts` | 合约列表 | - | `instrument_id`, `exchange`, `active_only` |
| `calendar` | 交易日历 | - | `exchange`（建议限定日期范围避免超时） |
| `readiness` | 就绪状态 | - | `exchange` |
| `dictionary` | 期货字典 | - | - |

### 9. query_futures_series - 期货序列

> 连续序列 series_id 在品种后加 `.main`，如 `CNF.AG.SHFE.main`。

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `series` | 连续序列列表 | - | `instrument_id`, `active_only` |
| `series_prices` | 序列价格（慢~30秒） | `series_id` | `start_date`, `end_date`, `limit` |
| `series_mapping` | 主力映射（慢~30秒） | `series_id` | `start_date`, `end_date`, `limit` |
| `cycle_diagnostics` | 周期诊断 | `series_id` | - |
| `default_prices` | 默认价格 | `instrument_id` | `start_date`, `end_date`, `limit` |
| `contract_prices` | 合约价格 | `contract_id` | `start_date`, `end_date`, `limit` |

### 10. query_commodity_data - 商品数据

> 商品序列 series_id 格式：`CMD.{大类}.{品种}.{期限}.{频率}`，如 `CMD.METAL.COPPER.LME3M.DAILY`（伦铜3月期日度）、`CMD.ENERGY.BRENT.DAILY`（布油）、`CMD.COAL.THERMAL.QINHUANGDAO.DAILY`（秦皇岛动力煤）、`CMD.FREIGHT.CCBFI.DAILY`（CCBFI运价指数）。
>
> 覆盖品种：海外主要有色（伦铜、伦铝、伦锌等）、能源（布油、WTI、天然气）、动力煤、港口基础运价（国内）等。

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `series` | 商品序列列表 | - | `active_only`(默认True) |
| `observations` | 序列观测值（慢~60秒） | `series_id` | `start_date`, `end_date` |
| `dictionary` | 商品字典 | - | - |
| `diagnostics` | 数据诊断 | - | - |
| `indicators` | 商品指标 | - | `category`, `series_id` |
| `policy_events` | 政策事件 | - | `commodity_id` |

### 11. query_fx_data - 外汇数据

> 外汇序列 series_id 格式：`FX.{货币对}.{来源}.{类型}.{频率}`，如 `FX.USD_CNY.CFETS.MID.DAILY`（人民币对美元中间价）、`FX.EUR_CNY.CFETS.MID.DAILY`（人民币对欧元）、`FX.JPY_CNY.CFETS.MID.DAILY`（人民币对日元）。
>
> 数据来源：CFETS（中国外汇交易中心）。支持双向换算和历史汇率查询。

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `series` | 外汇序列列表 | - | `active_only`(默认True) |
| `rates` | 汇率观测值 | `series_id` | `start_date`, `end_date`, `limit` |
| `convert` | 货币换算 | `from_currency`, `to_currency` | `amount`(默认1.0), `date`, `max_lag_days` |
| `indices` | 外汇指数列表 | - | - |
| `index_observations` | 指数观测值 | `series_id` | `start_date`, `end_date`, `limit` |
| `dictionary` | 外汇字典 | - | - |
| `readiness` | 就绪状态 | - | - |

### 12. query_risk_free_rate - 无风险利率

> 无风险利率 series_id 默认 `china_treasury_10y`（10年期国债收益率）。其他可选：`china_treasury_1y`、`china_treasury_3y`、`china_treasury_5y`、`china_treasury_30y` 等。
>
> 用于 DCF 估值、CAPM 模型等需要无风险利率假设的金融计算。

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `series` | 利率序列列表 | - | - |
| `rate` | 利率观测值 | - | `series_id`(默认china_treasury_10y), `start_date`, `end_date` |

### 13. query_financial_pit - 财务 PIT 面板

> **一句话定位**：在任意历史时点 T，一次调用返回全市场每只股票"截至 T 已公告的最新一期财务横截面"——每票自动回退到各自最新可知报告期，无未来函数（弱 PIT：时间严格、数值取最新口径并带更正防护）。
>
> 日期参数统一 **YYYYMMDD**（响应同格式）；同时兼容 `2026-08-01`、`2026/08/01` 写法，服务端自动归一化。

| action | 说明 | 必填参数 | 可选参数 |
|--------|------|---------|---------|
| `cross_section` | 时点横截面（主接口，热查询P95 <1s） | `as_of` | `report_period`, `exchange`(SSE/SZSE/BSE逗号分隔), `fields`(字段投影), `limit`(≤2000), `offset` |
| `panel` | 面板原始行分页（供本地全量缓存离线装配） | - | `report_period`, `instrument_id`, `available_at_lte`, `limit`(≤2000), `offset` |
| `coverage` | 覆盖与数据质量自检 | - | `report_period` |
| `changes` | 增量变更流（游标轮询，重放幂等） | - | `cursor`(首次省略), `limit` |

**时间语义**：`available_at` = 公告日（信息可知时点）；`effective_at` = 公告后**次一交易日**（执行时点语义，服务端已按交易日历 +1，客户端无需再加）。

**单位契约（勿再换算）**：`roe/gross_margin/operating_margin/net_margin/roa/asset_liability_ratio/rev_yoy/np_yoy` 为**百分数**（15.6 = 15.6%）；`eps/bps/ocfps/book_value_per_share` 为元（累计口径，**不预年化**）；`shares_outstanding` 为股（交叉验证后解析值）。

**数据质量字段**：

- `available_at_quality`：`exact`（真实披露日）> `exact_event` > `statutory_deadline`（法定截止日回退，方向保守）> `delayed_estimate`。2026Q2 起 exact 基本全覆盖，更早各期以 statutory 为主——做早期时点研究可只消费 `exact*`。
- `share_validation`：`consensus`（97.3%，可直接用）/ `discrepancy`（1.7%，锚间真实不一致，**建议剔除或人工核对**）/ `single_source`（~1%，无交叉验证）/ `null`（无可用锚，bps/ocfps 为 null）。
- `attribution_quality`：`parent`/`mixed`/`unverified`（归母口径标记）。
- `revised_after_publish` + `last_value_change_at`：更正防护，更正日前该期不可见。

**已知限制（如实声明）**：

- 报告期自 **2023-12-31 起 12 期**（更早仅6行稀疏数据），回测起点最早 2024 年初；
- universe 为**当前在市股票**（无退市股财务数据）——存在存活偏差，回测结论应表述为"在市集合内的因子排序证据"；
- 当期披露窗口内的最新一期可能不完整，以 `universe_note` 的 incomplete 标记与 coverage 的 `is_complete` 为准；
- BSE 覆盖较薄；`effective_at` 受交易日历视界限制（超界返回 null 而非近似）。

**推荐使用模式**：

1. **初次**：`panel` 翻页取全量（约6.6万行，实测 <2分钟）本地缓存；
2. **日常**：定时轮询 `changes?cursor=...`，对命中 (instrument_id, report_period) 重拉 panel 行；
3. **调仓日**：直接调 `cross_section`（服务端装配），或用本地缓存离线装配（同语义）。

**性能实测**：cross_section 热查询 P95 0.61s / 冷 3s；panel 2000行页 0.18s；coverage 1.6s。

> 详细对接指南见 `docs/financial_pit_panel_usage_guide.md`。

### 14. query_data_health - 数据健康自检

一次调用返回各数据集的最新业务日期、滞后交易日与新鲜度，替代"逐个接口试"。

| 参数 | 说明 | 默认 |
|------|------|------|
| `sample_stock` | 用于探测行情截止日的样本股 | `600519` |
| `risk_free_series_id` | 无风险利率序列 | `china_treasury_10y` |

返回结构：

| 字段 | 说明 |
|------|------|
| `backend` | 后端 `/health` 的 status、数据库行数、数据任务批次 |
| `datasets.quotes` | 最新行情日期、`staleness_trading_days`、`is_fresh`、来源、质量分 |
| `datasets.financial_pit` | `latest_complete_period`、覆盖数量、`universe_note` |
| `datasets.risk_free_rate` | 最新观测日期、滞后交易日、`is_fresh` |
| `all_fresh` | 所有已探测数据集是否都新鲜 |
| `criteria` | `is_fresh` 判定口径（行情 ≤1 个交易日、利率 ≤3 个交易日） |

> 单个数据集探测失败不影响其他数据集，失败项返回 `error` 字段。实测一次调用约 6-8 秒（含 PIT coverage 约 1.6-3 秒）。
>
> 未覆盖估值/技术指标：两者没有独立的数据集覆盖接口，其 `data_as_of` 与行情同源。

## 使用示例

### 示例 1：查询股票日度行情
```
查询贵州茅台（600519）2025年1月1日至2025年1月31日的日度行情数据
```

### 示例 2：获取最新行情
```
获取平安银行（000001）和招商银行（600036）的最新行情
```

### 示例 3：技术分析
```
分析宁德时代（300750）最近3个月的MACD、RSI和KDJ指标
```

### 示例 4：交易日历查询
```
查询上海证券交易所2025年1月的交易日历
```

### 示例 5：公司研究
```
查询贵州茅台（600519.SH）的行业归属和十大股东信息
```

## 数据源说明

本服务连接到股票数据 API 服务器：
- 基础 URL: `http://47.237.204.217:8000/api/v1`
- 支持的交易所：
  - SSE (上海证券交易所) - 股票代码以 6 开头
  - SZSE (深圳证券交易所) - 股票代码以 0 或 3 开头

## 项目结构

```
stock_server/
├── stock_mcp_integrated.py    # MCP服务主文件（含技术分析）
├── requirements.txt            # Python 依赖
├── start_server.sh            # Linux/macOS 启动脚本
├── start_server.bat           # Windows 启动脚本
└── README.md                  # 本文档
```

## 故障排除

### 问题 1：找不到模块 'fastmcp'

**解决方案：**
```bash
pip install fastmcp
```

### 问题 2：股票代码识别错误

**说明：**
- 上海证券交易所股票代码以 `6` 开头
- 深圳证券交易所股票代码以 `0` 或 `3` 开头
- 确保输入 6 位数字股票代码

### 问题 3：日期格式错误

**解决方案：**
使用 `YYYY-MM-DD` 格式，例如：`2025-01-05`

### 问题 4：技术指标返回大量 NA 值

**原因：**
技术指标需要足够的历史数据才能计算。例如：
- MA200 需要至少 200 个交易日数据
- MACD 需要至少 26 个交易日数据

**解决方案：**
服务会自动提前获取更多历史数据，但如果查询日期范围本身数据不足，仍会出现 NA 值。建议查询更长的日期范围。

### 问题 5：SSE模式端口被占用

**解决方案：**
```bash
# 使用其他端口
MCP_TRANSPORT=sse MCP_PORT=8092 python stock_mcp_integrated.py
```

### 问题 6：MCP 客户端无法连接

**检查项：**
1. stdio模式：确认 Python 环境正确，文件路径使用绝对路径
2. SSE模式：确认服务器防火墙放行对应端口，客户端配置正确的URL
3. 检查配置文件 JSON 格式是否正确
4. 查看 MCP 客户端日志获取详细错误信息

## 依赖项

```
requests>=2.32.5      # HTTP 请求
fastmcp>=2.14.1       # MCP 框架
typer>=0.12.3         # CLI 工具
pandas>=2.0.0         # 数据处理
numpy>=1.20.0         # 数值计算
```

## 版本历史

### v3.3.0 (2026-11-09)
- **行情复权口径派生（P0-1/P0-2/P0-3 调用方侧防护）**：`query_stock_quote.daily` 在 `factor != 1` 时为每行追加 `derived` 块（`close_raw` / `volume_raw` / `avg_price_raw` / `pct_change_decimal` 等），原始字段一个不改，避免调用方用 `close/pre_close-1` 或 `amount/volume` 静默算错
- **行情单位声明**：响应顶层新增 `units`（`pct_change=percent`、`amount=CNY`、`volume=shares`），并在 README 明示与 `query_stock_technical.pct_change_1d`（小数）相差100倍
- **`latest` 时点标识（P1-2）**：新增 `freshness` 块（`quote_type=snapshot` / `as_of` / `staleness_trading_days` / `is_same_trading_day` / `lag_source`），滞后天数用后端交易日历精确计算并缓存1小时
- **财务响应裁剪（P1-1）**：`query_stock_fundamental.financial` 默认 `summary_only=true`，响应从约190–280KB降到约2.3KB；新增 `fields` 字段投影（约1.4KB）；裁剪响应带 `_meta.omitted`，不静默丢数据；`financial_history` 同步支持 `fields`
- **新增数据健康自检工具 `query_data_health`（P1-3）**：一次返回后端状态、行情/财务PIT/无风险利率的最新业务日期、滞后交易日与 `is_fresh`，单数据集失败不影响其他数据集
- **Streamable HTTP 会话空闲回收**：新增 `MCP_SESSION_IDLE_TIMEOUT`（默认1800秒，≤0 关闭），解决会话只增不减、到进程退出才批量清理的问题
- **`daily` 停牌日过滤参数**：`query_stock_quote.daily` 新增 `include_suspended` / `min_quality_score` / `is_complete` / `min_volume`，均为后端参数透传；实测 `is_complete=true`、`min_volume=1` 可剔除停牌日（41行→20行），`include_suspended` / `min_quality_score` 后端未生效
- **未做（属后端职责）**：跨接口 `pct_change` 单位统一、`qfq` 复权未生效、`query_risk_free_rate` 的 `data_as_of` 恒为 null、`valuation/relative` 的 `peer_mean` 未剔除极端值、PIT 过滤参数（`min_available_at_quality`）、`include_suspended` / `min_quality_score` 过滤未生效——需后端实现，清单见 `docs/stock-server_后端数据问题与改造需求_20261109.md`
- 当前可用工具：14个；本轮25个校验用例全部通过

### v3.2.0 (2026-11-02)
- **新增财务 PIT 面板工具 `query_financial_pit`**：4个 action（`cross_section` / `panel` / `coverage` / `changes`），支持在任意历史时点 T 一次取回全市场"截至 T 已公告的最新一期财务横截面"，无未来函数，适用于量化回测调仓日因子取数
- **`query_industry_data` 新增 `as_of` 动作**：批量历史时点行业分类，用于行业中性化（不回填最新分类，避免未来函数）
- **`query_industry_data` 新增 `company_as_of` 动作**：单票历史时点行业归属，支持 `stock_code`/`instrument_id` 二选一
- 新增 6 个后端 API 客户端方法（4个 PIT 面板 + 批量时点行业 + 单票时点行业），均挂载在 `StockQuoteAPI` 类上，通过全局 `stock_api` 实例调用
- 新增 `_normalize_pit_date`（→ YYYYMMDD）与 `_to_iso_date`（→ YYYY-MM-DD）两个日期适配函数：后端批量时点接口要 YYYYMMDD、单票时点接口要 YYYY-MM-DD，本工具层自动适配，调用方三种写法均可
- 实测确认后端 6 个端点全部可用：cross_section（5522只）、panel（66133行/17期）、coverage、changes（游标 87→92 递增）、industries/as-of（5884只）、company/industry/as-of（茅台 340501 / 平安银行 480301，sw_2021）
- 附注1：`as_of` 时点行业的 `taxonomy_system` 取值为 `sw`（传 `sw2021` 会返回空集），与 `taxonomy` 动作的取值不同
- 附注2：`/research/company/{id}/financial-facts/as-of` 经实测为**空接口**（参数校验通过但恒返回 `total:0`，底层事实库无数据），**未接入**
- 当前可用工具：13个；PIT 面板17个功能用例、单票时点行业11个用例全部通过
- 详细对接说明见 `docs/financial_pit_panel_usage_guide.md`

### v3.1.0 (2026-07-18)
- **新增商品数据工具 `query_commodity_data`**：覆盖海外主要有色（伦铜/伦铝/伦锌）、能源（布油/WTI/天然气）、动力煤（秦皇岛港）、港口基础运价（CCBFI）等品种
- **新增外汇数据工具 `query_fx_data`**：覆盖人民币对美元/欧元/日元的中间价、汇率历史、双向换算、外汇指数等
- **新增无风险利率工具 `query_risk_free_rate`**：覆盖1/3/5/10/30年期国债收益率，默认 `china_treasury_10y`，支持 DCF/CAPM 计算
- 新增3类后端 API 客户端方法（商品/外汇/无风险利率），均挂载在 `StockQuoteAPI` 类上，通过全局 `stock_api` 实例调用
- 同步后端最新 openapi.json（121 个端点，新增 commodities/fx/risk-free-rate 三组）
- 修复聚合工具内部调用 NameError：原子方法挂载在 `StockQuoteAPI` 类上，必须通过 `stock_api.xxx()` 实例调用而非模块级调用
- 当前可用工具：12个（9原有 + 3新增），23个 action 测试用例全部通过
- 工具列表：query_stock_quote / query_stock_fundamental / query_stock_valuation / query_stock_beta / query_stock_technical / query_trading_calendar / query_industry_data / query_futures_basic / query_futures_series / query_commodity_data / query_fx_data / query_risk_free_rate

### v3.0.0 (2026-06-19)
- **架构升级**：参考 akshare-gateway 分级调用设计，将39个原子工具聚合为9个领域工具
- 通过 `action` 参数分发到具体子功能，对外暴露工具数从39降至9
- 大幅降低 LLM 上下文消耗，同时保留全部功能
- 原子工具函数保留供聚合工具内部调用，但不再对外注册为 MCP 工具
- 聚合工具列表：query_stock_quote / query_stock_fundamental / query_stock_valuation / query_stock_beta / query_stock_technical / query_trading_calendar / query_industry_data / query_futures_basic / query_futures_series
- 24个 action 测试用例全部通过

### v2.5.0 (2026-06-19)
- 统一所有公司研究和技术分析工具的参数：均支持 `stock_code`（6位代码）和 `instrument_id`（带后缀）二选一
- 新增 `_resolve_instrument_id` 辅助函数，自动处理两种参数名和格式转换
- 修复 `get_company_industry`、`get_financial_statements`、`get_shareholders` 等10个工具的参数兼容性
- 彻底解决参数名不匹配导致的 Pydantic 验证错误
- 当前可用工具：27个

### v2.3.0 (2026-06-19)
- 新增 `get_server_beta` 工具：服务端Beta，支持多窗口(60/120/252天)和多基准族
- 新增 `get_valuation_percentile` 工具：估值分位数，衡量当前估值在历史区间的相对位置
- 新增 `get_valuation_history` 工具：估值历史时间序列（PE/PB/PS等）
- 测试10个研究端点：3个可用(beta/valuation/percentile/valuation/history)已接入，7个不可用(503/404/500)未接入
- 当前可用工具：27个

### v2.5.0 (2026-06-19)
- 新增期货数据工具12个（期货模块后端已上线）
- 覆盖期货品种/合约/连续序列/价格/映射/周期诊断/日历/就绪状态/字典等全链路功能
- 期货 instrument_id 格式说明：`CNF.{品种}.{交易所}`（如 `CNF.AG.SHFE` 上海白银），连续序列加后缀 `.main`
- 当前可用工具：39个

### v2.4.0 (2026-06-19)
- 恢复 `get_shareholders` 工具（后端股东快照数据已可用）
- 恢复 `get_financial_statements_history` 工具，新增 `period_window` 参数（默认 latest）
- 修复财报历史接口卡死问题：默认 `include_statements=False` 轻量模式，超时设为 120 秒
- `_request`/`_research_request` 支持自定义 timeout 参数
- 同步后端最新 openapi.json（82 个端点）
- 当前可用工具：24个

### v2.1.0 (2026-05-30)
- 新增 Streamable HTTP 传输模式（MCP协议新标准，推荐）
- 新增回归Beta计算工具（本地计算，支持自定义基准和窗口）
- 恢复相对估值工具（后端已修复）
- 恢复DCF估值工具（后端已修复）
- 修复 `get_latest_stock_data` 参数兼容性（支持单个字符串或列表）
- 修复股票/指数代码区分（000001股票→SZ，000300指数→SH）
- 隐藏后端不可用工具（股东信息404、财务报表历史卡死）
- 启动脚本默认改为 Streamable HTTP 模式
- 当前可用工具：22个

### v2.0.0 (2026-06-14)
- 新增 SSE 传输模式，支持服务器部署
- 新增公司研究数据工具（行业、财务、股东）
- 新增服务端技术分析工具
- 新增行业研究数据工具
- 新增上/下一交易日本地计算
- 统一输入验证和异常处理
- 请求重试机制
- 默认端口 8091

### v1.0.0 (2026-04-22)
- 初始版本
- 支持股票数据查询
- 支持技术分析指标计算
- stdio 传输模式

## 许可证

本项目仅供学习和研究使用。

## 贡献

欢迎提交 Issue 和 Pull Request。
