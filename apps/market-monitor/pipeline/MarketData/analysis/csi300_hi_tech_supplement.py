# -*- coding: utf-8 -*-
"""补充：严格价格区间、本票自身、以及宏观高低端与科技股的联合方向"""
import json
import numpy as np
import pandas as pd

OUT = '/opt/daily-tasks/MarketData/analysis/out'
w = pd.read_csv(OUT + '/csi300_hi_tech_windows.csv', parse_dates=['start', 'end'])
w = w.dropna(subset=['tech_median'])
STOCK = 263.74 / 243.79 - 1

print('=== 1. 严格口径：csi300 价格落在 +23%~+28%（贴近总收益 +28.31% 的对应价 +25.49%）===')
strict = w[(w.csi_price_ret >= 0.23) & (w.csi_price_ret <= 0.28) & (w.tech_n >= 50)]
print('  窗口 %d 个，科技中位数 <= %+.2f%% 占 %.1f%%' %
      (len(strict), STOCK * 100, 100 * (strict.tech_median <= STOCK).mean()))
print('  科技中位数 中位 %+.2f%%｜全A中位数 中位 %+.2f%%｜csi300 中位 %+.2f%%' %
      (strict.tech_median.median() * 100, strict.all_median.median() * 100,
       strict.csi_price_ret.median() * 100))
print('  起点年份分布：', strict.start.dt.year.value_counts().sort_index().to_dict())

print('\n=== 2. 宏观低端：csi300 价格 <= −9.41%（对应报告低端总收益 −6.58%）===')
lo = w[(w.csi_price_ret <= -0.0941) & (w.tech_n >= 50)]
print('  窗口 %d 个｜科技中位数 中位 %+.2f%%｜全A中位 %+.2f%%｜csi300 中位 %+.2f%%' %
      (len(lo), lo.tech_median.median() * 100, lo.all_median.median() * 100,
       lo.csi_price_ret.median() * 100))
print('  科技中位数 >= +8.18%% 的占 %.1f%%（若显著高于高端窗，说明方向为负相关）' %
      (100 * (lo.tech_median >= STOCK).mean()))

hi = w[(w.csi_price_ret >= 0.23) & (w.tech_n >= 50)]
print('  对照：高端窗 %d 个，科技中位数 >= +8.18%% 的占 %.1f%%' %
      (len(hi), 100 * (hi.tech_median >= STOCK).mean()))
print('  相关系数 corr(csi300, 科技中位) = %+.4f（同一批日频重叠窗，仅作方向参考）' %
      w[['csi_price_ret', 'tech_median']].corr().iloc[0, 1])

print('\n=== 3. 本票 688200 在 csi300 高端窗口的自身表现 ===')
hf = w.dropna(subset=['hf_ret'])
hf_hi = hf[hf.csi_price_ret >= 0.23]
print('  本票可得窗口 %d 个，其中 csi300 高端 %d 个' % (len(hf), len(hf_hi)))
if len(hf_hi):
    print('  高端窗起点 %s ~ %s｜csi300 中位 %+.2f%%｜本票中位 %+.2f%%' %
          (hf_hi.start.min().date(), hf_hi.start.max().date(),
           hf_hi.csi_price_ret.median() * 100, hf_hi.hf_ret.median() * 100))
    print('  本票 <= %+.2f%% 的窗口 %d / %d = %.1f%%' %
          (STOCK * 100, (hf_hi.hf_ret <= STOCK).sum(), len(hf_hi),
           100 * (hf_hi.hf_ret <= STOCK).mean()))
    print('  本票相对 csi300 的差 中位 %+.2f pp' %
          ((hf_hi.hf_ret - hf_hi.csi_price_ret).median() * 100))

print('\n=== 4. 口径提醒 ===')
print('  沪深300 为市值加权价格指数；科技口径为个股等权横截面中位数。')
print('  二者的差同时包含「风格分化」与「加权方式差异」，不能全部读成科技股跑输。')
print('  报告 +28.31%/+8.75% 均为含息总回报；本脚本全部用价格口径，股息差约 2.8pp。')

json.dump(dict(n_strict=int(len(strict)),
               strict_sector_le_pct=float(100 * (strict.tech_median <= STOCK).mean()),
               lo_tech_median=float(lo.tech_median.median()),
               hi_tech_ge_pct=float(100 * (hi.tech_median >= STOCK).mean()),
               lo_tech_ge_pct=float(100 * (lo.tech_median >= STOCK).mean()),
               corr=float(w[['csi_price_ret', 'tech_median']].corr().iloc[0, 1]),
               n_hf_hi=int(len(hf_hi)),
               hf_hi_le_pct=float(100 * (hf_hi.hf_ret <= STOCK).mean()) if len(hf_hi) else None),
          open(OUT + '/csi300_hi_tech_supplement.json', 'w'), ensure_ascii=False, indent=2)
