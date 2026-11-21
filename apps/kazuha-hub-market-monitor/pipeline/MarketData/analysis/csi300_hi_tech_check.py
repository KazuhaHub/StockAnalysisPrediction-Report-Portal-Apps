# -*- coding: utf-8 -*-
"""检验：沪深300 12个月涨幅接近报告「高端」时，科技股整体/个股能否只涨约 9%。

口径纪律：
- 报告的 +28.31% 是【总收益】，对应价格 +25.49%（股息约 2.82pp）；本脚本用【价格收益】筛窗。
- 本票 +8.75% 是【总回报】，对应价格约 +8.19%（股息 1.38/243.79）。
- 因此比较对象：csi300 价格 >= +23%；科技价格中位数 <= +8.2%。
数据源：scripts/data/csi300_daily.json（价格指数）、~/MarketData（后复权个股日线）。
"""
import json, glob, os
import numpy as np
import pandas as pd

ROOT = '/opt/daily-tasks/MarketData'
CSI = '/opt/daily-tasks/WorkBuddy/2026-09-26-21-27-15/scripts/data/csi300_daily.json'
OUT = os.path.join(ROOT, 'analysis', 'out')
os.makedirs(OUT, exist_ok=True)

# ---------- 1. 沪深300 12 个月窗口（365 日历日，端点后置）----------
raw = json.load(open(CSI))
s = pd.Series(raw).sort_index()
s.index = pd.to_datetime(s.index)
dates = s.index
pos = np.searchsorted(dates.values, (dates + pd.Timedelta(days=365)).values)
ok = pos < len(dates)
w = pd.DataFrame({'start': dates[ok], 'end': dates[pos[ok]],
                  'csi_price_ret': s.values[pos[ok]] / s.values[ok] - 1})
print('csi300 覆盖 %s ~ %s，共 %d 点；12m 窗口 %d 个' %
      (dates[0].date(), dates[-1].date(), len(s), len(w)))

# ---------- 2. 个股后复权收盘宽表 ----------
frames = []
for f in sorted(glob.glob(os.path.join(ROOT, 'bars', '*.parquet'))):
    x = pd.read_parquet(f, columns=['code', 'date', 'close', 'volume'])
    frames.append(x[x['volume'] > 0])          # 停牌日剔除，避免假收益
df = pd.concat(frames, ignore_index=True)
panel = df.pivot(index='date', columns='code', values='close').sort_index()
panel.index = pd.to_datetime(panel.index)
del df, frames
print('个股宽表 %s ~ %s，%d 日 × %d 票' %
      (panel.index[0].date(), panel.index[-1].date(), *panel.shape))

meta = json.load(open(os.path.join(ROOT, 'meta.json')))['stocks']
TECH_SW1 = {'电子', '计算机', '通信'}
tech = [c for c, v in meta.items() if v.get('sw1') in TECH_SW1 and c in panel.columns]
allc = [c for c in meta if c in panel.columns]
print('科技口径（申万一级 电子/计算机/通信）%d 票；全库 %d 票' % (len(tech), len(allc)))

# ---------- 3. 每个窗口的横截面收益 ----------
P0 = panel.reindex(w['start'].values, method='ffill')
P1 = panel.reindex(w['end'].values, method='ffill')
P0.index = w.index          # 两端索引统一，否则除法会取并集
P1.index = w.index
R = (P1 / P0 - 1)
Rt, Ra = R[tech], R[allc]

w['tech_median'] = Rt.median(axis=1).values
w['tech_mean'] = Rt.mean(axis=1).values
w['all_median'] = Ra.median(axis=1).values
w['tech_n'] = Rt.notna().sum(axis=1).values
w['tech_frac_le_stock'] = (Rt <= (263.74 / 243.79 - 1)).sum(axis=1).values / Rt.notna().sum(axis=1).values
w['hf_ret'] = R['688200'].values if '688200' in R.columns else np.nan

# ---------- 4. 高端窗口 ----------
HI = 0.23          # 价格口径：对应总收益 ~+25.8%，贴近报告的 +28.31%
STOCK = 263.74 / 243.79 - 1     # +8.19% 价格
hi_w = w[(w['csi_price_ret'] >= HI) & (w['tech_n'] >= 50)].copy()
hi_w['gap'] = hi_w['tech_median'] - hi_w['csi_price_ret']

print('\n=== 4.1 沪深300 价格涨幅 >= %.0f%% 的 12m 窗口：%d 个（日频、高度重叠）===' %
      (HI * 100, len(hi_w)))
print('  日期范围 %s ~ %s' % (hi_w['start'].min().date(), hi_w['start'].max().date()))
print('  csi300 价格收益 中位 %.2f%% / 区间 %.2f%%~%.2f%%' %
      (hi_w['csi_price_ret'].median() * 100, hi_w['csi_price_ret'].min() * 100,
       hi_w['csi_price_ret'].max() * 100))
print('  科技股横截面【中位数】收益 中位 %.2f%% / 区间 %.2f%%~%.2f%%' %
      (hi_w['tech_median'].median() * 100, hi_w['tech_median'].min() * 100,
       hi_w['tech_median'].max() * 100))
print('  全A 中位数 中位 %.2f%%' % (hi_w['all_median'].median() * 100))

n_sector = (hi_w['tech_median'] <= STOCK).sum()
print('\n=== 4.2 板块层面：科技中位数 <= 本票价格回报 +%.2f%% 的窗口 ===' % (STOCK * 100))
print('  %d / %d = %.1f%%' % (n_sector, len(hi_w), 100 * n_sector / len(hi_w)))
if n_sector:
    hit = hi_w.loc[hi_w['tech_median'] <= STOCK]
    print('  命中窗口起点范围 %s ~ %s' % (hit['start'].min().date(), hit['start'].max().date()))
    # 按起点间隔 > 90 天切成独立行情段，避免把同一段行情的数百个重叠窗口当样本
    seg, cur = [], []
    for d in sorted(hit['start']):
        if cur and (d - cur[-1]).days > 90:
            seg.append(cur); cur = []
        cur.append(d)
    if cur: seg.append(cur)
    print('  → 合并为 %d 段独立行情（起点间隔 >90 天切分）：' % len(seg))
    for g in seg:
        sub = hi_w[hi_w['start'].isin(g)]
        best = sub.iloc[(sub['csi_price_ret'] - 0.2549).abs().argmin()]
        print('    %s ~ %s｜%d 个重叠窗｜代表窗 csi300 %+.2f%% 科技中位 %+.2f%% 全A中位 %+.2f%%' %
              (g[0].date(), g[-1].date(), len(g), best['csi_price_ret'] * 100,
               best['tech_median'] * 100, best['all_median'] * 100))
    summary_segs = [dict(start=str(g[0].date()), end=str(g[-1].date()), n_windows=len(g))
                    for g in seg]
else:
    summary_segs = []

print('\n=== 4.3 个股层面：科技股中涨幅 <= +%.2f%% 的比例 ===' % (STOCK * 100))
print('  横截面比例 中位 %.1f%% / 区间 %.1f%%~%.1f%%' %
      (hi_w['tech_frac_le_stock'].median() * 100,
       hi_w['tech_frac_le_stock'].min() * 100, hi_w['tech_frac_le_stock'].max() * 100))

# ---------- 5. 不重叠窗口（每年一个，起点年末）----------
w2 = w.copy()
w2['yr'] = w2['start'].dt.year
norep = w2.drop_duplicates(subset='yr', keep='last')
norep_hi = norep[(norep['csi_price_ret'] >= HI) & (norep['tech_n'] >= 50)]
print('\n=== 5. 不重叠年度窗口（消除重叠，样本极少）===')
print('  高端窗口 %d 个：' % len(norep_hi))
print(norep_hi[['start', 'end', 'csi_price_ret', 'tech_median',
                'tech_frac_le_stock']].to_string(index=False) if len(norep_hi) else '  （无）')

# ---------- 6. 本票自身（2020-02 上市后）----------
hf = w.dropna(subset=['hf_ret'])
print('\n=== 6. 本票 688200 可得窗口 %d 个（%s 起）===' %
      (len(hf), hf['start'].min().date() if len(hf) else '-'))
if len(hf):
    print('  csi300 同期价格收益 中位 %.2f%%，本票 中位 %.2f%%' %
          (hf['csi_price_ret'].median() * 100, hf['hf_ret'].median() * 100))
    print('  本票跑输指数 20pp 以上的窗口 %d / %d' %
          ((hf['hf_ret'] - hf['csi_price_ret'] < -0.20).sum(), len(hf)))

# ---------- 7. 落盘 ----------
cols = ['start', 'end', 'csi_price_ret', 'tech_median', 'tech_mean', 'all_median',
        'tech_n', 'tech_frac_le_stock', 'hf_ret']
w[cols].to_csv(os.path.join(OUT, 'csi300_hi_tech_windows.csv'), index=False)
summary = dict(price_threshold=HI, stock_price_ret=STOCK,
               n_hi_windows=int(len(hi_w)),
               n_sector_le=int(n_sector),
               sector_le_pct=float(100 * n_sector / len(hi_w)) if len(hi_w) else None,
               tech_median_in_hi=float(hi_w['tech_median'].median()) if len(hi_w) else None,
               all_median_in_hi=float(hi_w['all_median'].median()) if len(hi_w) else None,
               frac_tech_le_stock_median=float(hi_w['tech_frac_le_stock'].median()) if len(hi_w) else None,
               n_nonoverlap_hi=int(len(norep_hi)),
               independent_segments=summary_segs)
json.dump(summary, open(os.path.join(OUT, 'csi300_hi_tech_summary.json'), 'w'),
          ensure_ascii=False, indent=2)
print('\n结果已写入 analysis/out/')
