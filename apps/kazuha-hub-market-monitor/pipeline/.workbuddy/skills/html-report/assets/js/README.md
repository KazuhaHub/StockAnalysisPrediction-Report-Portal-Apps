# Shared JS Libraries

Place minified JS libraries here for report authoring:

- `echarts.min.js` — ECharts charting library (5.5.1)
- `chart-boot.js` — chart bootstrap layer: `CHART(id, option)` mount, layout wait,
  per-chart error isolation, auto-resize, missing-library fallback
- `mermaid.min.js` — Mermaid diagram library

## Serving modes

**Multi-file mode** — copy into the report and reference relatively:

```html
<script src="./_shared/js/echarts.min.js"></script>
<script src="./_shared/js/chart-boot.js"></script>
```

**Single-file offline mode (default for finance deep-dive reports)** — reference by
bare filename and let `scripts/build_report.py` inline the real content:

```html
<script src="echarts.min.js"></script>
<script src="chart-boot.js"></script>
```

Never reference a CDN. `cdn.jsdelivr.net` is unreachable on common networks
(`Connection reset`), which silently blanks every chart in the report.
