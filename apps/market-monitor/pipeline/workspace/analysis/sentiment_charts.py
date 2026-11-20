#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 assets/charts.js（数据内嵌，保证单文件离线可用）。"""
import json

D = json.load(open("/opt/daily-tasks/workspace/reports/market-sentiment/assets/data.json", encoding="utf-8"))
OUT = "/opt/daily-tasks/workspace/reports/market-sentiment/assets/charts.js"

tpl = r"""/* eslint-disable */
(function () {
  var cs = getComputedStyle(document.documentElement);
  var accent = cs.getPropertyValue('--accent').trim() || '#B33A2B';
  var accent2 = cs.getPropertyValue('--accent2').trim() || '#1F4E5F';
  var ink = cs.getPropertyValue('--ink').trim() || '#1A1A1A';
  var muted = cs.getPropertyValue('--muted').trim() || '#6B6B6B';
  var rule = cs.getPropertyValue('--rule').trim() || '#DDD9D1';
  var bg = cs.getPropertyValue('--bg').trim() || '#FBFAF8';
  var bg2 = cs.getPropertyValue('--bg2').trim() || '#F3F1EC';

  var AX = {
    axisLine: { lineStyle: { color: rule } },
    axisLabel: { color: muted, fontSize: 11 },
    splitLine: { lineStyle: { color: rule, type: 'dashed', opacity: .55 } }
  };
  var TIP = { trigger: 'axis', appendToBody: true, backgroundColor: '#fff', borderColor: rule,
              textStyle: { color: ink, fontSize: 12 }, extraCssText: 'box-shadow:0 2px 12px rgba(0,0,0,.08);' };

  /* ============ 图1 PPI / CPI ============ */
  var PPI = __PPI__;
  CHART('chart-ppi', {
    animation: false,
    tooltip: Object.assign({}, TIP, { valueFormatter: function (v) { return v == null ? '—' : v + '%'; } }),
    legend: { data: ['PPI 当月同比', 'CPI 当月同比'], textStyle: { color: muted, fontSize: 11 }, top: 0 },
    grid: { left: 48, right: 24, top: 40, bottom: 46 },
    xAxis: Object.assign({ type: 'category', data: PPI.months, boundaryGap: false,
      axisLabel: { color: muted, fontSize: 10, interval: 3 } }, { axisLine: AX.axisLine }),
    yAxis: Object.assign({ type: 'value', name: '%', nameTextStyle: { color: muted, fontSize: 11 } }, AX),
    series: [
      { name: 'PPI 当月同比', type: 'line', data: PPI.ppi, smooth: false, symbol: 'none',
        lineStyle: { width: 2.4, color: accent },
        areaStyle: { color: accent, opacity: .07 },
        markLine: { silent: true, symbol: 'none',
          label: { show: true, position: 'insideStartTop', color: muted, fontSize: 10, formatter: 'PPI 零轴' },
          data: [{ yAxis: 0, lineStyle: { color: muted, type: 'dashed', width: 1 } }] } },
      { name: 'CPI 当月同比', type: 'line', data: PPI.cpi, smooth: false, symbol: 'none',
        connectNulls: true, itemStyle: { color: accent2 },
        lineStyle: { width: 2.2, color: accent2, type: 'dashed' } }
    ]
  });

  /* ============ 图2 IC 对比 ============ */
  var IC = __IC__;
  CHART('chart-ic', {
    animation: false,
    tooltip: Object.assign({}, TIP),
    legend: { data: ['同期 IC（对当日收益）', '组内预测 IC（对 fwd20）'], textStyle: { color: muted, fontSize: 11 }, top: 0 },
    grid: { left: 46, right: 24, top: 44, bottom: 76 },
    xAxis: Object.assign({ type: 'category', data: IC.names,
      axisLabel: { color: muted, fontSize: 10, interval: 0, rotate: 34 } }, { axisLine: AX.axisLine }),
    yAxis: Object.assign({ type: 'value', name: 'Spearman IC', nameTextStyle: { color: muted, fontSize: 11 } }, AX),
    series: [
      { name: '同期 IC（对当日收益）', type: 'bar', data: IC.raw, barGap: '10%',
        itemStyle: { color: accent, opacity: .85 } },
      { name: '组内预测 IC（对 fwd20）', type: 'bar', data: IC.within,
        itemStyle: { color: accent2, opacity: .85 },
        markLine: { silent: true, symbol: 'none', label: { show: false },
          data: [{ yAxis: 0, lineStyle: { color: ink, width: 1 } }] } }
    ]
  });

  /* ============ 图3 雷达 ============ */
  var RD = __RADAR__;
  CHART('chart-radar', {
    animation: false,
    tooltip: Object.assign({}, TIP, { trigger: 'item' }),
    legend: { data: ['当前 2026-11-13', '2018-01-31（最相似）', '历史中位'], textStyle: { color: muted, fontSize: 11 }, top: 0 },
    radar: {
      indicator: RD.dims.map(function (d) { return { name: d, max: 100 }; }),
      radius: '62%', center: ['50%', '56%'],
      axisName: { color: ink, fontSize: 12, fontWeight: 600 },
      splitLine: { lineStyle: { color: rule } },
      splitArea: { areaStyle: { color: [bg, bg2] } },
      axisLine: { lineStyle: { color: rule } }
    },
    series: [{
      type: 'radar',
      data: [
        { value: RD.cur, name: '当前 2026-11-13',
          lineStyle: { color: accent, width: 2.6 }, itemStyle: { color: accent },
          areaStyle: { color: accent, opacity: .16 } },
        { value: RD.near2018, name: '2018-01-31（最相似）',
          lineStyle: { color: accent2, width: 1.8, type: 'dashed' }, itemStyle: { color: accent2 },
          areaStyle: { color: accent2, opacity: .05 } },
        { value: RD.median, name: '历史中位',
          lineStyle: { color: muted, width: 1.2, type: 'dotted' }, itemStyle: { color: muted }, areaStyle: { opacity: 0 } }
      ]
    }]
  });

  /* ============ 图4 条件分布热力图 ============ */
  var CD = __COND__;
  var hd = CD.cells.map(function (c) { return [c[0], c[1], c[2]]; });
  CHART('chart-cond', {
    animation: false,
    tooltip: Object.assign({}, TIP, {
      trigger: 'item',
      formatter: function (p) {
        var v = p.value[2];
        return CD.x[p.value[0]] + ' · ' + CD.y[p.value[1]] + '<br/>' +
          (v === '-' ? '样本不足（<20 个交易日），不参与比较' : 'fwd20 中位：<b>' + v + '%</b>');
      }
    }),
    grid: { left: 88, right: 96, top: 26, bottom: 56 },
    xAxis: { type: 'category', data: CD.x, splitArea: { show: false },
      axisLabel: { color: ink, fontSize: 12 }, axisLine: { lineStyle: { color: rule } }, splitLine: { show: false } },
    yAxis: { type: 'category', data: CD.y, splitArea: { show: false },
      axisLabel: { color: ink, fontSize: 11 }, axisLine: { lineStyle: { color: rule } }, splitLine: { show: false } },
    visualMap: {
      min: -2.6, max: 5.6, calculable: false, orient: 'vertical', right: 12, top: 'center',
      itemWidth: 13, itemHeight: 120, text: ['+5.6%', '-2.6%'], textStyle: { color: muted, fontSize: 10 },
      inRange: { color: ['#1E7A4B', '#8FBBA6', '#F3F1EC', '#D99C90', '#C0392B'] },
      outOfRange: { color: 'transparent' }
    },
    series: [{
      type: 'heatmap', data: hd,
      label: { show: true, color: ink, fontSize: 13, fontWeight: 700,
        formatter: function (p) { return p.value[2] === '-' ? 'N/A' : p.value[2].toFixed(2) + '%'; } },
      itemStyle: { borderColor: bg, borderWidth: 3 },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,.2)' } }
    }]
  });

  /* ============ 图5 时序 ============ */
  var TS = __TS__;
  CHART('chart-ts', {
    animation: false,
    tooltip: Object.assign({}, TIP, { valueFormatter: function (v) { return v == null ? '—' : v + '%'; } }),
    legend: { data: ['站上 MA250 比例', '资金集中度分位', '每股成交额分位'], icon: 'roundRect',
      itemWidth: 14, itemHeight: 3, textStyle: { color: muted, fontSize: 11 }, top: 0 },
    grid: { left: 44, right: 20, top: 46, bottom: 40 },
    xAxis: Object.assign({ type: 'category', data: TS.dates, boundaryGap: false,
      axisLabel: { color: muted, fontSize: 10, interval: 11 } }, { axisLine: AX.axisLine }),
    yAxis: Object.assign({ type: 'value', max: 100, name: '%', nameTextStyle: { color: muted, fontSize: 11 } }, AX),
    series: [
      { name: '站上 MA250 比例', type: 'line', data: TS.above250, symbol: 'none', connectNulls: true,
        smooth: true, itemStyle: { color: accent2 },
        lineStyle: { width: 2.4, color: accent2 }, areaStyle: { color: accent2, opacity: .08 } },
      { name: '资金集中度分位', type: 'line', data: TS.conc, symbol: 'none', connectNulls: true,
        smooth: true, itemStyle: { color: accent }, lineStyle: { width: 2, color: accent } },
      { name: '每股成交额分位', type: 'line', data: TS.amt, symbol: 'none', connectNulls: true,
        smooth: true, itemStyle: { color: muted }, lineStyle: { width: 1.4, color: muted, type: 'dashed' } }
    ]
  });

  /* ============ 图6 2026 季度（上下双格） ============ */
  var Q = __Q26__;
  var qk = Object.keys(Q);
  CHART('chart-q', {
    animation: false,
    tooltip: Object.assign({}, TIP),
    legend: { data: ['资金集中度分位', '广度（above250）', '每股成交额分位'],
      textStyle: { color: muted, fontSize: 11 }, top: 0 },
    grid: [
      { left: 52, right: 28, top: 52, height: '42%' },
      { left: 52, right: 28, top: '70%', height: '17%' }
    ],
    xAxis: [
      { type: 'category', gridIndex: 0, data: qk, axisLabel: { show: false }, axisLine: { lineStyle: { color: rule } }, axisTick: { show: false } },
      { type: 'category', gridIndex: 1, data: qk, axisLabel: { color: ink, fontSize: 12 }, axisLine: { lineStyle: { color: rule } }, axisTick: { show: false } }
    ],
    yAxis: [
      Object.assign({ type: 'value', gridIndex: 0, max: 100, name: '情绪分位 %',
        nameTextStyle: { color: muted, fontSize: 11 } }, AX),
      Object.assign({ type: 'value', gridIndex: 1, name: '季度收益 %', min: -9, max: 3, interval: 3,
        nameTextStyle: { color: muted, fontSize: 11 } }, AX)
    ],
    series: [
      { name: '资金集中度分位', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, barWidth: '14%',
        data: qk.map(function (k) { return Q[k].conc; }), itemStyle: { color: accent, opacity: .9 } },
      { name: '广度（above250）', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, barWidth: '14%',
        data: qk.map(function (k) { return Q[k].b250; }), itemStyle: { color: accent2, opacity: .9 } },
      { name: '每股成交额分位', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, barWidth: '14%',
        data: qk.map(function (k) { return Q[k].amt; }), itemStyle: { color: muted, opacity: .55 } },
      { name: '等权组合收益', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, barWidth: '26%',
        data: qk.map(function (k) { return Q[k].ret; }),
        itemStyle: { color: function (p) { return p.value >= 0 ? '#C0392B' : '#1E7A4B'; }, opacity: .9 },
        label: { show: true, position: 'top', color: ink, fontSize: 11, fontWeight: 700,
          formatter: function (p) { return p.value + '%'; } },
        markLine: { silent: true, symbol: 'none', label: { show: false },
          data: [{ yAxis: 0, lineStyle: { color: rule, width: 1 } }] } }
    ]
  });

  /* ============ 图7 事件路径 ============ */
  var PA = __PATH__;
  var fullDays = [], curPad = [];
  for (var i = 0; i <= 20; i++) { fullDays.push(i); curPad.push(i < PA.cur.length ? PA.cur[i] : null); }
  CHART('chart-path', {
    animation: false,
    tooltip: Object.assign({}, TIP, {
      formatter: function (ps) {
        var s = '触发后第 ' + ps[0].axisValue + ' 个交易日<br/>';
        ps.forEach(function (p) { s += p.marker + p.seriesName + '：<b>' + (p.value == null ? '—' : p.value + '%') + '</b><br/>'; });
        return s;
      }
    }),
    legend: { data: ['当前（2026-10-29 触发）', '历史 15 簇中位'], textStyle: { color: muted, fontSize: 11 }, top: 0 },
    grid: { left: 50, right: 30, top: 46, bottom: 46 },
    xAxis: Object.assign({ type: 'category', data: fullDays }, { axisLine: AX.axisLine }),
    yAxis: Object.assign({ type: 'value', name: '%', min: -3.5, max: 7,
      nameTextStyle: { color: muted, fontSize: 11 } }, AX),
    series: [
      { name: '当前（2026-10-29 触发）', type: 'line', data: curPad, connectNulls: false, symbol: 'circle', symbolSize: 5,
        lineStyle: { width: 2.6, color: accent }, itemStyle: { color: accent },
        areaStyle: { color: accent, opacity: .08 } },
      { name: '历史 15 簇中位', type: 'line', data: PA.hist, symbol: 'none',
        lineStyle: { width: 2, color: accent2, type: 'dashed' }, itemStyle: { color: accent2 } }
    ]
  });
})();
"""

js = (tpl
      .replace("__PPI__", json.dumps(D["ppi"], ensure_ascii=False))
      .replace("__IC__", json.dumps(D["ic"], ensure_ascii=False))
      .replace("__RADAR__", json.dumps(D["radar"], ensure_ascii=False))
      .replace("__COND__", json.dumps(D["cond"], ensure_ascii=False))
      .replace("__TS__", json.dumps(D["ts"], ensure_ascii=False))
      .replace("__Q26__", json.dumps(D["q2026"], ensure_ascii=False))
      .replace("__PATH__", json.dumps(D["path"], ensure_ascii=False)))

open(OUT, "w", encoding="utf-8").write(js)
print("写出", OUT, len(js), "bytes")
