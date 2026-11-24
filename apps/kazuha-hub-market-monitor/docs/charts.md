# Chart and number colours

Every chart and signed number in the market-monitor frontend follows the
conventions A-share readers see every day in 同花顺, 东方财富 and Wind. The
rules live in one place, `frontend/src/components/useVisual.ts`, and in the
`Signed` component (`frontend/src/components/Signed.tsx`); charts take their
colours from there and never hard-code them.

## 1. Up and down: red and green, and nothing else

- Red (`v.up`, the theme's error colour) is up, inflow, positive. Green
  (`v.down`, the theme's success colour) is down, outflow, negative. Both
  come from theme tokens, so they work in dark mode.
- This applies everywhere a value has a sign: bars, areas, KPI numbers and
  their captions, table cells, deltas, arrows. Decide per metric by meaning:
  a change, gap, return, drawdown or flow is signed; a level (breadth, a
  share of turnover, a percentile, a count, a price or index level, a
  position) is not and stays the default text colour. A positive number is red with a "+", a
  negative one green with "-", zero in the default text colour, a missing one
  "—". Use `<Signed value digits suffix scale />` in tables and drawers,
  `<SignedIn template value />` for a number inside a caption, and
  `color: v.sign(x)` on KPI items.
- Red and green carry no other meaning in a chart. A highlight that is not a
  sign (a bin over a threshold, a hot reading) is amber (`v.orange`).
- Candlesticks (none today): up red, down green, solid; a volume bar takes the
  colour of its day's candle.

## 2. Series identity never uses red or green

- Lines and categories are told apart by `v.series`, always in this order:
  primary blue, amber (gold-7), purple (purple-7), teal (cyan-7), gray, then
  magenta-7 and geekblue-7. It is also the default ECharts palette, so a
  series without an explicit colour follows it. The level-7 tokens are
  lightened by antd's dark algorithm and keep contrast on both backgrounds.
- A strategy, NAV or the series the chart is about is primary blue. A
  benchmark, buy-and-hold or index line is gray (`v.series[4]`).

## 3. Moving averages

As terminals draw them, in thin lines (width 1) from `v.ma`:
MA5 the text colour, MA10 amber, MA20 magenta, MA60 teal (this app uses teal
for MA60), MA120 geekblue, MA200 gray.

## 4. Secondary series and thresholds

- A right-axis series (breadth or a percentage next to an index or price) is
  lighter, thinner or dashed in its series colour; the price or index is the
  primary line.
- Thresholds and reference lines use `v.threshold`, a neutral gray dashed
  line, with a label saying what they are.

## 5. Signal markers

Direction follows meaning. Every bullish signal is a red upward triangle and
every bearish one a green downward triangle, in the chart and in the legend.
When several bearish types share a chart they stay downward triangles and are
told apart by fill (hollow or solid) and a small label, never by switching
shape. Neutral marks (a state switch) are gray ticks. Every chart with markers
shows them in its legend, and the tooltip names the signal.

## 6. Statuses and state labels

A status (a signal light, a state, a risk level, a valuation verdict) is not a
sign, so it is never red or green. `v.status` / `v.statusTag` in
`useVisual` give the colours:

- failed / off / neutral: gray; watch or warning: amber; usable or
  opportunity: blue; the most severe warning: strong orange (`v.alert`).
- Margin: 高危 and 临界 strong orange (solid tag), 关注 and 潜伏 amber, 已去杠杆
  blue, 安全 gray.
- Valuation: 显著低估 blue, 低估 cyan, 合理 gray, 高估 amber, 显著高估 strong
  orange (solid tag).
- Quant states, one tone shared by the chart bands, the table text and the
  tags (`stateTone` in lib/quant.ts): 熊市/下跌 purple, 警戒/过热 amber, 出清
  cyan, 确认/修复 blue, 常规 gray. ETF 信号状态: 失效 gray, 观察 amber, 可用
  blue.
- The most severe level is a solid tag (`tagProps("orange-inverse")` in
  lib/status.ts gives antd's `variant="solid"`) or a strong-orange border; a
  warning is the default amber tag, so the two read apart.
- Signed numbers inside running text use the rich-text markup
  `[[up:+1.2]]` / `[[down:-1.2]]` (`sx` in lib/quant.ts).
- Valuation quadrants: 便宜好公司 blue, 优质但贵 amber, 价值陷阱 purple, 又贵又差
  strong orange. Check boxes and run results: passed blue, failed strong
  orange. A percentile heat map (not a sign) runs blue to amber.
- A signed series' legend swatch is neutral gray: its bars are red and green
  by sign.

## 7. Numbers and titles

- Amounts in 亿 or 万 as the terminals show them (`formatYi`), sensible
  decimals, percentages with their sign.
- Titles, legends and hints never name colours ("（红）", "red line"); they name
  the series or the shape ("实线 = 现价", "倒三角 = 资金退潮").
