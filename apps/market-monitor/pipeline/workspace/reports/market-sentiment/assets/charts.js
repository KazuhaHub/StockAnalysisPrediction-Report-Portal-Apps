/* eslint-disable */
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
  var PPI = {"months": ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06", "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"], "ppi": [-2.5, -2.7, -2.8, -2.5, -1.4, -0.8, -0.8, -1.8, -2.8, -2.9, -2.5, -2.3, -2.3, -2.2, -2.5, -2.7, -3.3, -3.6, -3.6, -2.9, -2.3, -2.1, -2.2, -1.9, -1.4, -0.9, 0.5, 2.8, 3.9, 4.1, 3.5, 3.8, 5.0, 5.7], "cpi": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, 0.2, 1.3, 1.0, 1.2, 1.2, 1.0, 0.5, 0.8, 0.9, 0.7]};
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
  var IC = {"names": ["上涨家数占比", "成交额/20日均", "已实现波动率", "横截面离散度", "跌停家数", "250日新低占比", "20日正收益占比", "站上MA20比例", "站上MA60比例", "站上MA250比例"], "raw": [0.055, 0.106, 0.121, 0.076, -0.064, -0.091, 0.027, 0.066, -0.014, -0.025], "within": [0.006, 0.038, 0.138, 0.002, 0.015, 0.072, -0.097, -0.045, -0.189, -0.353]};
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
  var RD = {"dims": ["量能", "广度", "极端", "赚钱效应", "资金结构"], "cur": [47.1, 14.9, 15.7, 27.2, 88.1], "near2018": [44.3, 16.6, 17.2, 23.5, 86.4], "median": [49.5, 46.6, 47.1, 45.3, 56.3]};
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
  var CD = {"x": ["集中度低", "中", "高"], "y": ["广度<10%", "10-20%", "20-35%", ">35%"], "cells": [[0, 0, "-", 16], [1, 0, -0.74, 40], [2, 0, -2.56, 69], [0, 1, 4.6, 79], [1, 1, 5.6, 96], [2, 1, 1.44, 135], [0, 2, -0.52, 159], [1, 2, 3.49, 91], [2, 2, -0.83, 353], [0, 3, -0.76, 543], [1, 3, 0.36, 534], [2, 3, 1.11, 663]]};
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
  var TS = {"dates": ["2019-01-31", "2019-02-28", "2019-03-31", "2019-04-30", "2019-05-31", "2019-06-30", "2019-07-31", "2019-08-31", "2019-09-30", "2019-10-31", "2019-11-30", "2019-12-31", "2020-01-31", "2020-02-29", "2020-03-31", "2020-04-30", "2020-05-31", "2020-06-30", "2020-07-31", "2020-08-31", "2020-09-30", "2020-10-31", "2020-11-30", "2020-12-31", "2021-01-31", "2021-02-28", "2021-03-31", "2021-04-30", "2021-05-31", "2021-06-30", "2021-07-31", "2021-08-31", "2021-09-30", "2021-10-31", "2021-11-30", "2021-12-31", "2022-01-31", "2022-02-28", "2022-03-31", "2022-04-30", "2022-05-31", "2022-06-30", "2022-07-31", "2022-08-31", "2022-09-30", "2022-10-31", "2022-11-30", "2022-12-31", "2023-01-31", "2023-02-28", "2023-03-31", "2023-04-30", "2023-05-31", "2023-06-30", "2023-07-31", "2023-08-31", "2023-09-30", "2023-10-31", "2023-11-30", "2023-12-31", "2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31", "2024-06-30", "2024-07-31", "2024-08-31", "2024-09-30", "2024-10-31", "2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-31", "2025-06-30", "2025-07-31", "2025-08-31", "2025-09-30", "2025-10-31", "2025-11-30", "2025-12-31", "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30", "2026-10-31", "2026-11-30"], "above250": [10.7, 29.3, 69.5, 81.4, 50.9, 52.8, 54.8, 40.3, 55.7, 47.2, 34.9, 39.8, 53.9, 39.3, 40.7, 36.4, 39.1, 46.4, 70.2, 78.3, 70.2, 63.9, 60.3, 50.9, 37.3, 31.9, 38.5, 39.2, 39.9, 43.5, 44.0, 49.9, 56.9, 48.0, 51.3, 64.7, 64.9, 54.4, 42.5, 28.0, 23.0, 33.8, 40.3, 42.7, 32.6, 25.2, 36.4, 38.6, 42.4, 63.9, 59.9, 50.4, 44.6, 43.6, 49.7, 45.6, 42.0, 33.2, 43.7, 39.0, 24.4, 11.5, 21.2, 22.2, 28.1, 20.6, 16.7, 14.9, 17.7, 64.3, 83.5, 86.0, 64.5, 77.5, 81.3, 62.2, 74.1, 76.7, 85.0, 89.3, 83.6, 77.8, 78.1, 68.4, 78.4, 76.4, 63.0, 53.4, 51.0, 33.1, 21.7, 24.5, 25.4, 16.1, 13.7], "above60": [42.5, 74.0, 98.5, 88.8, 17.7, 16.8, 30.8, 26.5, 59.0, 44.6, 27.7, 48.2, 82.9, 43.0, 39.1, 29.8, 35.7, 56.9, 86.7, 83.6, 43.9, 32.0, 36.3, 33.7, 27.4, 25.9, 45.5, 56.3, 51.4, 58.8, 50.1, 51.5, 58.7, 35.3, 42.7, 63.6, 54.8, 34.1, 26.2, 19.5, 22.1, 60.4, 70.8, 57.2, 29.6, 20.2, 50.4, 53.4, 49.8, 79.0, 56.8, 36.8, 32.4, 37.5, 54.1, 41.7, 33.2, 27.5, 56.7, 42.1, 22.9, 15.5, 42.9, 44.9, 53.5, 21.5, 15.4, 25.0, 44.3, 97.0, 95.8, 73.7, 18.8, 43.3, 62.9, 30.8, 49.2, 61.8, 83.0, 85.5, 61.5, 49.9, 50.1, 37.5, 65.8, 64.9, 41.2, 30.6, 41.2, 24.0, 17.3, 45.4, 53.9, 26.7, 22.7], "conc": [62.1, 56.5, 40.2, 41.9, 67.9, 71.9, 72.3, 82.8, 62.8, 72.3, 86.1, 72.4, 46.8, 62.3, 49.6, 55.3, 63.8, 64.2, 52.3, 31.5, 32.3, 62.0, 74.8, 87.3, 98.3, 97.9, 88.8, 83.5, 89.6, 86.0, 92.1, 85.8, 74.3, 84.8, 54.6, 27.3, 15.9, 34.6, 35.2, 22.1, 26.2, 36.1, 35.8, 10.6, 10.7, 18.1, 10.8, 16.7, 33.4, 5.7, 46.0, 73.0, 65.7, 64.3, 45.2, 47.6, 36.1, 53.4, 22.2, 13.0, 12.6, 8.9, 42.0, 23.8, 21.9, 50.8, 73.3, 55.0, 53.5, 70.9, 58.5, 28.1, 68.9, 83.8, 17.7, 7.3, 6.4, 13.2, 16.0, 41.5, 94.3, 89.7, 67.1, 87.1, 77.6, 83.3, 70.9, 93.4, 98.6, 99.7, 97.5, 92.8, 83.1, 69.8, 79.4], "amt": [9.0, 58.6, 94.6, 89.7, 48.7, 40.2, 26.0, 37.8, 64.7, 33.2, 28.7, 55.6, 89.3, 95.9, 90.7, 75.6, 72.7, 84.6, 97.4, 92.6, 75.0, 73.4, 81.7, 80.0, 92.3, 85.9, 73.3, 65.1, 77.4, 83.8, 91.7, 94.8, 93.3, 74.3, 79.3, 76.7, 67.8, 54.8, 61.5, 47.1, 43.1, 73.7, 57.7, 53.9, 18.1, 23.9, 38.8, 22.2, 19.5, 31.8, 38.0, 70.3, 35.0, 35.8, 19.9, 18.3, 6.5, 20.7, 24.3, 13.0, 11.3, 45.0, 54.2, 41.3, 30.2, 11.5, 7.9, 6.7, 26.4, 99.0, 97.4, 94.3, 83.9, 95.5, 88.6, 75.7, 75.7, 80.6, 89.9, 95.5, 96.6, 93.1, 88.0, 86.0, 98.5, 91.1, 89.4, 88.2, 97.8, 95.9, 87.0, 75.4, 59.9, 50.3, 55.7]};
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
  var Q = {"Q1": {"conc": 77.0, "b250": 75.0, "amt": 94.0, "ret": 0.6}, "Q2": {"conc": 99.0, "b250": 50.0, "amt": 96.0, "ret": -6.3}, "Q3": {"conc": 93.0, "b250": 24.0, "amt": 72.0, "ret": -1.5}, "Q4": {"conc": 74.0, "b250": 15.0, "amt": 51.0, "ret": -7.7}};
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
  var PA = {"cur": [0.0, -2.61, -0.34, -0.82, 1.43, 3.51, 1.85, 1.9, 3.33, 4.23, 2.73, 0.8], "hist": [0.0, -0.1, -0.41, -0.63, 0.82, 1.43, 0.85, 2.77, 3.68, 1.49, 3.29, -0.04, 0.85, 1.24, 1.83, 2.89, 4.92, 5.9, 4.6, 6.67, 4.42], "days": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]};
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
