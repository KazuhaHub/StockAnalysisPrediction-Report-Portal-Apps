# analysis · 读库出结论的脚本

这里的脚本都**只读** `~/MarketData`，不改数据；结果统一写到 `out/`，可以随时重跑。
凡是「数字要进报告」的地方都从脚本现算，不手抄。

```bash
cd ~/MarketData/analysis
/opt/daily-tasks/venv/bin/python3 pool_effect.py     # 需要 pandas/pyarrow
```

> 解释器必须用 `/opt/daily-tasks/venv/bin/python3`（3.9 + pandas）。
> PATH 里默认的 `python3` 是 3.13，跑不了。

---

## 1. 脚本清单

| 脚本 | 回答什么问题 | 输出 |
|---|---|---|
| `pool_effect.py` | **池子多大才够用**：同一批信号、同一区间，只换标的池（全库 vs 55 只小池），t 值差多少 | `out/pool_effect.csv` |
| `ic_by_regime.py` | 动量/反转的 IC 是结构性还是阶段性：分年度、分市场状态各算一遍横截面 IC | 终端（+ 供 `export_chart_data.py` 用） |
| `weight_lag.py` | 复刻公募的因子权重机制（滚动 60 日 IC 定权），**风格切换后权重转向要几个交易日** | `out/weight_lag.csv`、`out/ic_series.csv` |
| `dividend_event.py` | 红利指数大跌是不是「入手机会」：事件研究 + 全样本基准率 + 随机日期安慰剂 | `out/dividend_event.csv` |
| `two_pool_check.py` | `qsr stab` 的稳定性判级能不能提前认出「换池会改口」的信号（真实双池对照，A=1,492 / B=1,988） | `out/two_pool.json` |
| `export_stab_data.py` | 稳定性报告的图表数据，全部从引擎现跑 | `out/stab_chart_data.json` |
| `export_chart_data.py` | 把 IC / 权重序列导成报告的 `assets/data.js` | 报告目录（写死路径） |
| `build_pool.py` | 把库导成 skill 的池格式 JSON | `/tmp/klines_*.json`（故意不落库，几百 MB） |
| `backfill_marketdata.py` | 一次性补票（进程内调用 add，避开 shell 参数聚合的坑） | — 已被 `expand_run.py` 取代 |

## 2. 结果怎么看

**`pool_effect.csv`** — 每行 = 一个信号 × 一个池，字段 `n_stocks / n_days / mean_diff_bp / t / t_nw / avg_n_sig / win`。
用法：看同一个信号在两个池上的 `t` 差多少，判断「池子扩容会不会改口」。

**`weight_lag.csv`** — 每个交易日一行：`w_mom / w_rev` 是当天由滚动 IC 决定的因子权重，
`lag_trading_days` 从风格切换日算起。用法：找权重过零点，就是「转向需要几天」。
同源产出 `ic_series.csv`（`date, ic_mom, ic_rev, w_mom, w_rev`），画时间序列用。

**`dividend_event.csv`** — `event_mean / base_mean / excess / placebo_pct`。
`placebo_pct` 是随机抽同样数量日期后超额收益落在多少分位：**接近 1 说明事件本身没什么特别**，
只是那段行情整体如此。

**`two_pool.json`** — 每条信号在池 A / 池 B 上各算主口径 Δ 与 t，附 `qsr stab` 的 `grade/scope`。
用法：看「判级低的信号，换池后改口的比例是不是更高」——这是判级有没有预测力的唯一硬检验。

## 3. 加新脚本的约定

1. 顶部写清「回答什么问题」，不要只写「分析」；
2. 路径用绝对路径或 `os.path.dirname(__file__)`，不要依赖 cwd；
3. 结果落 `out/`，中间大文件落 `/tmp`；
4. 不写数据、只在 `out/` 里加文件——要改库请走 `market_data.py`（有快照与守卫）。
