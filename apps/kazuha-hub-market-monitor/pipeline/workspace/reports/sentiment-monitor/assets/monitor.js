/* 市场情绪监控面板渲染层
   数据来自 assets/monitor-data.js 注入的 window.MONITOR
   图表一律走 CHART()（chart-boot.js），不要直接 echarts.init */
(function () {
  var M = window.MONITOR;
  if (!M) {
    document.body.insertAdjacentHTML('afterbegin',
      '<p style="padding:20px;color:#C0392B">monitor-data.js 未加载</p>');
    return;
  }

  var C = { hot: '#C0392B', cold: '#1E7A4B', warm: '#C98A1E', cool: '#2C6E8F',
            ink: '#1B1A17', ink2: '#4A463E', muted: '#8A8378', rule: '#E2DDD2',
            card: '#FFFFFF', bg: '#F5F3EE' };

  var TIP = {
    backgroundColor: 'rgba(27,26,23,.94)', borderWidth: 0,
    textStyle: { color: '#F5F3EE', fontSize: 12 },
    padding: [8, 11], extraCssText: 'border-radius:3px;'
  };
  function AX() {
    return {
      axisLine: { lineStyle: { color: C.rule } },
      axisTick: { show: false },
      axisLabel: { color: C.muted, fontSize: 10.5 },
      splitLine: { lineStyle: { color: '#F0EDE6' } }
    };
  }
  function f1(v) { return (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(1); }
  function signed(v, d) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    var s = Number(v).toFixed(d === undefined ? 1 : d);
    return (v > 0 ? '+' : '') + s;
  }

  /* ---------- 1. header / 新鲜度 ---------- */
  document.getElementById('asof').textContent = M.asof;
  (function () {
    var el = document.getElementById('fresh');
    var today = new Date();
    var d = new Date(M.asof + 'T00:00:00');
    var gap = Math.round((today - d) / 86400000);
    if (gap <= 1) {
      el.textContent = '· 最新交易日';
    } else {
      el.className = 'warn';
      el.textContent = '· 距今日 ' + gap + ' 天未更新';
    }
  })();

  /* ---------- 2. hero ---------- */
  document.getElementById('headline').textContent = M.headline;
  document.getElementById('herosub').innerHTML =
    '组合格「' + M.cell.b + ' × ' + M.cell.c + '」历史 20 日中位 <b>' +
    signed(M.cell.v, 2) + '%</b>（' + M.cell.n + ' 个交易日）；' +
    '五维离散度 <b>' + M.disp.v + 'pp</b>，历史 ' + M.disp.rank + '% 分位' +
    '——结构分化到这种程度，任何合成指数都会失真。';

  /* ---------- 3. KPI ---------- */
  var D = {};
  M.dims.forEach(function (x) { D[x.k] = x; });
  var kpi = [];
  var bRead = M.extreme.filter(function (e) { return e.name === '站上 MA250'; })[0];
  kpi.push({
    lab: '广度（站上 MA250）',
    num: (bRead ? bRead.v : '—'),
    cls: 'c-cold',
    sub: '三年分位 ' + (bRead ? bRead.pct : '—') + '% · 阈值 15% 为极冷'
  });
  kpi.push({
    lab: '资金集中度分位',
    num: D['资金结构'].v.toFixed(0) + '<em>/100</em>',
    cls: 'c-hot',
    sub: '越高＝钱越抱团，出清越难'
  });
  var S = M.signal;
  kpi.push({
    lab: '广度极冷信号',
    num: (S.active ? '第 ' + S.days + '<em>日</em>' : '已解除'),
    cls: S.active ? 'c-warm' : 'c-cold',
    sub: S.active ? ('自 ' + S.trigger + ' 累计 ' + signed(S.ret_since, 2) + '%')
                  : ('上轮持续 ' + S.days + ' 日')
  });
  var pathGap = null;
  if (S.active && S.path.length && S.cur_path.length) {
    var di = Math.min(S.cur_path.length - 1, S.path.length - 1);
    pathGap = S.cur_path[di] - S.path[di];
  }
  kpi.push({
    lab: '路径偏离',
    num: (pathGap === null ? '—' : signed(pathGap, 1) + '<em>pp</em>'),
    cls: (pathGap !== null && pathGap < 0) ? 'c-cold' : 'c-hot',
    sub: '当前累计收益 − 历史同类中位路径'
  });
  document.getElementById('kpis').innerHTML = kpi.map(function (k) {
    return '<div class="kpi"><div class="lab">' + k.lab + '</div>' +
      '<div class="num ' + k.cls + '">' + k.num + '</div>' +
      '<div class="sub">' + k.sub + '</div></div>';
  }).join('');

  /* ---------- 4. 五维条 ---------- */
  function heatBand(v) {
    if (v < 10) return '#14713F';
    if (v < 30) return '#3F8A63';
    if (v < 50) return '#6E8F86';
    if (v < 70) return '#B08F4A';
    if (v < 85) return '#C07514';
    return '#B0311E';
  }
  function arrow(chg) {
    if (chg > 2) return '<span class="up">↑' + signed(chg) + 'pp</span>';
    if (chg < -2) return '<span class="down">↓' + signed(chg) + 'pp</span>';
    return '<span class="flat">→' + signed(chg) + 'pp</span>';
  }
  document.getElementById('dims').innerHTML = M.dims.map(function (x) {
    return '<div class="dim">' +
      '<div class="dim-k">' + x.k + '<span>' + x.desc.split('\uff08')[0] + '</span></div>' +
      '<div class="bar">' +
        '<i style="width:' + x.v + '%;background:' + heatBand(x.v) + '"></i>' +
        '<b style="left:20%"></b><b style="left:80%"></b>' +
      '</div>' +
      '<div class="dim-v" style="color:' + heatBand(x.v) + '">' + x.v.toFixed(0) + '</div>' +
      '<div class="dim-chg">' + arrow(x.chg5) + '</div>' +
      '<div class="dim-note">' + x.verdict + ' · 20 日前 ' + x.d20.toFixed(0) + ' → 今日 ' + x.v.toFixed(0) + '</div>' +
      '</div>';
  }).join('');

  /* ---------- 5. 组合格热力 ---------- */
  var G = M.grid;
  var cellsOk = [], cellsNA = [];
  var vmax = 0.1, vmin = -0.1;
  G.cells.forEach(function (row, i) {
    row.forEach(function (c, j) {
      var cur = !!c.cur;
      if (c.v === null) {
        cellsNA.push([j, i, 0, cur ? 1 : 0, c.n]);
      } else {
        cellsOk.push({
          value: [j, i, c.v, cur ? 1 : 0, c.n],
          label: cur ? { backgroundColor: C.ink, color: '#FFFFFF', padding: [4, 7], borderRadius: 2 }
                     : { color: C.ink }
        });
        if (c.v > vmax) vmax = c.v;
        if (c.v < vmin) vmin = c.v;
      }
    });
  });
  CHART('chart-grid', {
    animation: false,
    tooltip: Object.assign({}, TIP, {
      trigger: 'item',
      formatter: function (p) {
        if (!p.value) return '';
        var v = p.value[2];
        return G.x[p.value[0]] + ' × ' + G.y[p.value[1]] + '<br/>' +
          (v === null ? '样本不足（&lt;20 个交易日）' : 'fwd20 中位：<b>' + v.toFixed(2) + '%</b>') +
          '<br/><span style="opacity:.65">' + p.value[4] + ' 个交易日</span>';
      }
    }),
    grid: { left: 78, right: 76, top: 18, bottom: 36 },
    xAxis: {
      type: 'category', data: G.x, splitArea: { show: false },
      axisLabel: { color: C.ink, fontSize: 11.5 },
      axisLine: { lineStyle: { color: C.rule } }, splitLine: { show: false }
    },
    yAxis: {
      type: 'category', data: G.y, inverse: true, splitArea: { show: false },
      axisLabel: { color: C.ink2, fontSize: 11 },
      axisLine: { lineStyle: { color: C.rule } }, splitLine: { show: false }
    },
    visualMap: {
      seriesIndex: 0,
      dimension: 2,
      min: Math.floor(vmin * 10) / 10, max: Math.ceil(vmax * 10) / 10,
      calculable: false, orient: 'vertical', right: 8, top: 'center',
      itemWidth: 11, itemHeight: 92,
      text: [signed(vmax) + '%', signed(vmin) + '%'],
      textStyle: { color: C.muted, fontSize: 9.5 },
      inRange: { color: ['#1E7A4B', '#8FBBA6', '#F3F1EC', '#D99C90', '#C0392B'] }
    },
    series: [
      {
        type: 'heatmap', data: cellsOk, z: 1,
        label: {
          show: true, color: C.ink, fontSize: 12.5, fontWeight: 700,
          formatter: function (p) { return signed(p.value[2], 2) + '%'; }
        },
        itemStyle: { borderWidth: 2, borderColor: C.card },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,.18)' } }
      },
      {
        type: 'heatmap', data: cellsNA, z: 3, silent: true,
        itemStyle: { color: '#EDEAE3', borderWidth: 2, borderColor: C.card },
        label: { show: true, color: C.muted, fontSize: 11, formatter: 'N/A' }
      }
    ]
  });

  /* ---------- 6. 信号路径 ---------- */
  var days = [];
  for (var i = 0; i <= 20; i++) days.push(i);
  var curPad = days.map(function (i) {
    return i < S.cur_path.length ? S.cur_path[i] : null;
  });
  var histPad = days.map(function (i) {
    return i < S.path.length ? S.path[i] : null;
  });
  CHART('chart-path', {
    animation: false,
    tooltip: Object.assign({}, TIP, {
      trigger: 'axis',
      formatter: function (ps) {
        var out = '第 ' + ps[0].axisValue + ' 个交易日';
        ps.forEach(function (p) {
          if (p.value !== null && p.value !== undefined && !isNaN(p.value)) {
            out += '<br/>' + p.marker + p.seriesName + '：<b>' + signed(p.value, 2) + '%</b>';
          }
        });
        return out;
      }
    }),
    legend: {
      data: ['本轮', '历史 ' + S.hist_n + ' 簇中位'],
      icon: 'roundRect', itemWidth: 13, itemHeight: 3,
      textStyle: { color: C.muted, fontSize: 10.5 }, top: 0, right: 0
    },
    grid: { left: 46, right: 16, top: 34, bottom: 40 },
    xAxis: Object.assign({
      type: 'category', data: days, boundaryGap: false,
      axisLabel: { color: C.muted, fontSize: 10, interval: 2, margin: 9 }
    }, { axisLine: AX().axisLine, axisTick: { show: false } }),
    yAxis: Object.assign({
      type: 'value', name: '%', min: -4, max: 8, interval: 2,
      nameTextStyle: { color: C.muted, fontSize: 10 }
    }, AX()),
    series: [
      {
        name: '历史 ' + S.hist_n + ' 簇中位', type: 'line', data: histPad,
        symbol: 'none', smooth: true, connectNulls: true,
        itemStyle: { color: '#8A8378' },
        lineStyle: { width: 1.8, color: '#8A8378', type: 'dashed' }
      },
      {
        name: '本轮', type: 'line', data: curPad, connectNulls: false,
        symbol: 'circle', symbolSize: 4, smooth: false,
        itemStyle: { color: C.hot },
        lineStyle: { width: 2.4, color: C.hot },
        areaStyle: { color: C.hot, opacity: .07 }
      }
    ]
  });
  document.getElementById('pathcap').innerHTML =
    '阈值：站上 MA250 占比 &lt; 15%。本轮起点 ' + S.trigger + '，已走 ' +
    (S.cur_path.length - 1) + ' 个交易日；历史 ' + S.hist_n +
    ' 簇第 20 日中位 ' + signed(S.hist_med20, 2) + '%，胜率 ' + S.hist_win20 + '%。';

  /* ---------- 7. 预警 ---------- */
  var LAB = { red: 'RED', amber: 'WATCH', green: 'OK', gray: 'INFO' };
  document.getElementById('alerts').innerHTML = M.alerts.map(function (a) {
    return '<div class="alert ' + a.level + '">' +
      '<div class="t"><i>' + (LAB[a.level] || 'INFO') + '</i>' + a.title + '</div>' +
      '<p>' + a.body + '</p></div>';
  }).join('');

  /* ---------- 8. 极端读数 ---------- */
  function pctColor(p) {
    if (p >= 85) return C.hot;
    if (p >= 65) return C.warm;
    if (p <= 15) return C.cold;
    if (p <= 35) return '#5E9C7F';
    return '#B7B0A4';
  }
  document.querySelector('#ext tbody').innerHTML = M.extreme.map(function (e) {
    return '<tr><td>' + e.name + '</td>' +
      '<td style="font-weight:700">' + e.v + '</td>' +
      '<td class="pctcell"><div class="track">' +
        '<i style="width:' + e.pct + '%;background:' + pctColor(e.pct) + '"></i></div>' +
        '<em>' + e.pct + '% 分位</em></td></tr>';
  }).join('');

  /* ---------- 9. 近一年轨迹 ---------- */
  var T = M.traj, keys = Object.keys(T.series);
  function ma5(a) {
    var out = [], q = [], sum = 0;
    for (var i = 0; i < a.length; i++) {
      var v = a[i];
      if (v === null || v === undefined) { out.push(null); continue; }
      q.push(v); sum += v;
      if (q.length > 5) sum -= q.shift();
      out.push(Math.round(sum / q.length * 10) / 10);
    }
    return out;
  }
  var COL = { '量能': '#2C6E8F', '广度': '#1E7A4B', '极端': '#C98A1E',
              '赚钱效应': '#8E5AA8', '资金结构': '#C0392B' };
  CHART('chart-traj', {
    animation: false,
    tooltip: Object.assign({}, TIP, {
      trigger: 'axis',
      formatter: function (ps) {
        var out = ps[0].axisValue;
        ps.forEach(function (p) {
          if (p.value !== null && p.value !== undefined) {
            out += '<br/>' + p.marker + p.seriesName + '：<b>' + f1(p.value) + '</b>';
          }
        });
        return out;
      }
    }),
    legend: {
      data: keys, icon: 'roundRect', itemWidth: 13, itemHeight: 3,
      textStyle: { color: C.muted, fontSize: 10.5 }, top: 0
    },
    grid: { left: 40, right: 22, top: 40, bottom: 32 },
    xAxis: Object.assign({
      type: 'category', data: T.dates, boundaryGap: false,
      axisLabel: { color: C.muted, fontSize: 10, interval: 40 }
    }, { axisLine: AX().axisLine, axisTick: { show: false } }),
    yAxis: Object.assign({
      type: 'value', name: '分位', min: 0, max: 100, interval: 25,
      nameTextStyle: { color: C.muted, fontSize: 10 }
    }, AX()),
    series: keys.map(function (k) {
      return {
        name: k, type: 'line', data: ma5(T.series[k]), symbol: 'none',
        smooth: true, connectNulls: true,
        lineStyle: { width: (k === '资金结构' || k === '广度') ? 2.4 : 1.4,
                     color: COL[k], opacity: (k === '资金结构' || k === '广度') ? 1 : 0.72 },
        itemStyle: { color: COL[k] },
        emphasis: { focus: 'series' },
        markLine: k === '资金结构' ? {
          silent: true, symbol: 'none',
          lineStyle: { color: C.rule, width: 1, type: 'solid' },
          label: { show: false },
          data: [{ yAxis: 20 }, { yAxis: 80 }]
        } : undefined
      };
    })
  });
})();
