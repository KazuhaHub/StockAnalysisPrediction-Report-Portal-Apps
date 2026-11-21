/* 融资盘压力扫描 — 前端逻辑
 * 依赖全局 PAYLOAD（由 build_data.py 生成）
 * 图表一律走 CHART(id, option)，由 chart-boot.js 负责挂载与容错
 */
(function () {
  'use strict';

  var P = window.PAYLOAD;
  if (!P || !P.rows || !P.rows.code) {
    document.getElementById('kpis').innerHTML =
      '<div style="padding:24px;color:#f6465d">数据未加载：payload.js 缺失或损坏。</div>';
    return;
  }

  var F = P.fields, R = P.rows, N = R.code.length;
  var OV = P.overview, META = P.meta, HD = P.hist_dates || [];

  /* ---------------- 组装 ---------------- */
  var S = new Array(N);
  for (var i = 0; i < N; i++) {
    var o = { _i: i };
    for (var j = 0; j < F.length; j++) { o[F[j]] = R[F[j]][i]; }
    o._k = String(o.name) + ' ' + String(o.code) + ' ' + String(o.py || '');
    S[i] = o;
  }

  /* ---------------- 工具 ---------------- */
  function fx(v, d) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Number(v).toFixed(d === undefined ? 2 : d);
  }
  function sgn(v, d) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    var s = Number(v).toFixed(d === undefined ? 2 : d);
    return (v > 0 ? '+' : '') + s;
  }
  function cls(v) { return v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dim'); }
  function sx(v) { return sgn(v, 1); }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function sum(arr) { var t = 0; for (var i = 0; i < arr.length; i++) t += arr[i]; return t; }
  function avg(arr) { return arr.length ? sum(arr) / arr.length : NaN; }
  function med(arr) {
    if (!arr.length) return NaN;
    var a = arr.slice().sort(function (x, y) { return x - y; });
    var m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  }

  /* ---------------- 顶部 ---------------- */
  document.getElementById('asof').textContent = META.as_of_date;
  document.getElementById('nstock').textContent = N.toLocaleString('en-US');
  document.getElementById('tot').textContent = N.toLocaleString('en-US');

  /* ---------------- 分组 ---------------- */
  var byState = {};
  S.forEach(function (o) { (byState[o.state] = byState[o.state] || []).push(o); });
  var crit = byState['临界'] || [];
  var latent = byState['潜伏'] || [];
  var flushed = byState['已去杠杆'] || [];
  var hiList = S.filter(function (o) { return o.level === '高危'; });
  var waList = S.filter(function (o) { return o.level === '关注'; });
  var rzOf = function (arr) { return sum(arr.map(function (o) { return o.rz || 0; })); };
  var rzAll = rzOf(S);
  var over8 = S.filter(function (o) { return o.ratio > 8; });

  /* ---------------- KPI ---------------- */
  var KPI = [
    {
      lb: '融资余额合计', vl: fx(rzAll / 10000, 2), u: '万亿',
      sub: '近 20 日 ' + sgn(OV.rz_chg20_total, 1) + '%（全市场口径）',
      c: OV.rz_chg20_total > 0 ? 'warn' : 'cool'
    },
    {
      lb: '占流通市值中位数', vl: fx(OV.ratio_med, 2), u: '%',
      sub: 'P90 ' + fx(OV.ratio_p90, 1) + '% · P99 ' + fx(OV.ratio_p99, 1) + '%', c: ''
    },
    {
      lb: '浮亏逼近理论追保线', vl: String(OV.n_critical), u: '只',
      sub: '合计 ' + fx(rzOf(crit) / 10000, 2) + ' 万亿 · 状态标签，非下跌预警',
      c: 'hot'
    },
    {
      lb: '杠杆拥挤且仍在抬升', vl: String(OV.n_latent), u: '只',
      sub: '合计 ' + fx(rzOf(latent) / 10000, 2) + ' 万亿 · 状态标签', c: 'warn'
    },
    {
      lb: '浮亏越过理论追保线', vl: String(OV.n_flushed), u: '只',
      sub: '平均浮亏 ' + fx(avg(flushed.map(function (o) { return o.pnl; })), 1) + '% · 压力已释放',
      c: ''
    },
    {
      lb: '全市场平均维持担保比例', vl: fx(OV.guarantee, 0), u: '%',
      sub: OV.guarantee_date + ' · 理论追保线 150%（仅极端账户）',
      c: OV.guarantee < 200 ? 'warn' : 'cool'
    }
  ];
  document.getElementById('kpis').innerHTML = KPI.map(function (k) {
    return '<div class="kpi ' + k.c + '">' +
      '<div class="lb">' + k.lb + '</div>' +
      '<div class="vl num">' + k.vl + '<span class="u">' + k.u + '</span></div>' +
      '<div class="sub">' + k.sub + '</div></div>';
  }).join('');

  /* ---------------- KPI 第二排：持仓结构 ---------------- */
  var plNear = S.filter(function (o) { return o.pld_room > 0 && o.pld_room <= 15; });
  var plBreach = S.filter(function (o) { return o.pld_room <= 0; });
  var ulkBig = S.filter(function (o) { return o.ulk60 >= 5; });
  var ulkMv = sum(ulkBig.map(function (o) { return (o.ulk60 || 0) / 100 * (o.fcap || 0); }));
  var fundCrowd = S.filter(function (o) { return o.fund_pct > 20; });
  var crowdRet = med(fundCrowd.map(function (o) { return o.ret20; }));
  var resList = S.filter(function (o) { return o.res_cnt >= 2; });

  var KPI2 = [
    {
      lb: '两类强平线共振', vl: String(OV.n_res2 || 0), u: '只',
      sub: '融资强平 + 质押强平同处现价下方 25%', c: 'hot'
    },
    {
      lb: '质押贴近平仓线', vl: String(plNear.length), u: '只',
      sub: '距线 15% 内 · 另有 ' + plBreach.length + ' 只已破线', c: 'warn'
    },
    {
      lb: '60 日解禁 >5% 流通', vl: String(ulkBig.length), u: '只',
      sub: '合计 ' + fx(ulkMv, 0) + ' 亿 · 中位占流通 ' +
        fx(med(ulkBig.map(function (o) { return o.ulk60; })), 0) + '%', c: 'warn'
    },
    {
      lb: '公募重仓 >20% 流通', vl: String(fundCrowd.length), u: '只',
      sub: '这组近 20 日涨跌中位 ' + sgn(crowdRet, 1) + '%',
      c: crowdRet < 0 ? 'hot' : ''
    }
  ];
  document.getElementById('kpis2').innerHTML = KPI2.map(function (k) {
    return '<div class="kpi ' + k.c + '">' +
      '<div class="lb">' + k.lb + '</div>' +
      '<div class="vl num">' + k.vl + '<span class="u">' + k.u + '</span></div>' +
      '<div class="sub">' + k.sub + '</div></div>';
  }).join('');

  /* ---------------- 结论 ---------------- */
  var dropAdd = S.filter(function (o) { return o.tags && o.tags.indexOf('价跌加杠杆') >= 0; });
  var fragTop = S.slice().sort(function (a, b) { return b.frag - a.frag; }).slice(0, 30);
  var latentFrag = latent.slice().sort(function (a, b) { return b.frag - a.frag; }).slice(0, 20);

  var V = [
    '杠杆总量 <b>' + fx(rzAll / 10000, 2) + ' 万亿</b>，占全市场流通市值中位数 <b>' + fx(OV.ratio_med, 2) + '%</b>。' +
      '但<b>方向比水平重要</b>：120 个交易日前是 <b>' + fx((OV.lever_series.rz[0] || 0) / 10000, 2) + ' 万亿</b>，' +
      '近 20 日又降 <b class="g">' + sgn(OV.rz_chg20_total, 1) + '%</b>——半年去杠杆约 ' +
      fx((1 - OV.lever_series.rz[OV.lever_series.rz.length - 1] / OV.lever_series.rz[0]) * 100, 0) +
      '%，且仍在加速。存量出清已经做了一大半，这是判断当前处境的前提。',

    '总量不极端，结构极端：占比 &gt;8% 的 <b class="r">' + over8.length + '</b> 只标的吃掉了 <b>' +
      fx(rzOf(over8) / rzAll * 100, 1) + '%</b> 的融资盘，P99 已达 <b class="r">' + fx(OV.ratio_p99, 1) +
      '%</b>。按最激进假设，浮亏已越过理论追保线的有 ' + OV.n_flushed + ' 只（平均浮亏 ' +
      fx(avg(flushed.map(function (o) { return o.pnl; })), 1) + '%），另有 ' + OV.n_critical +
      ' 只落在距理论追保线 15% 以内的状态区间。这是浮亏深度的分布，不是风险倒计时。',

    '<b>只看融资盘会系统性低估抛压来源。</b>' +
      '未来 60 日解禁超流通市值 5% 的有 <b class="r">' + ulkBig.length + '</b> 只、合计 <b>' +
      fx(ulkMv, 0) + ' 亿</b>（中位占流通 ' + fx(med(ulkBig.map(function (o) { return o.ulk60; })), 0) + '%）；' +
      '质押盘距平仓线 15% 以内的 <b class="r">' + plNear.length + '</b> 只、另有 <b>' + plBreach.length +
      '</b> 只已经跌穿。这些机制<b>都不在两融数据里</b>。',

    '最锋利的一刀是<b>成本线共振</b>：<b class="r">' + resList.length + '</b> 只标的的融资追保线与质押平仓线' +
      '同时落在现价下方 25% 以内（合计融资余额 ' + fx(rzOf(resList), 0) + ' 亿，质押比例中位 ' +
      fx(med(resList.map(function (o) { return o.pld_ratio; })), 0) + '%）。' +
      '再跌一段，卖压来自两套互不相干的账户——<b>这不是情绪问题，是合同问题</b>。全市场只有这么多，值得逐一看。',

    '另一类是融资盘完全不覆盖的资金：公募重仓占流通 &gt;20% 的 <b>' + fundCrowd.length + '</b> 只，' +
      '这组近 20 日涨跌中位 <b class="g">' + sgn(crowdRet, 1) + '%</b>。它们的卖压来自<b>赎回机制</b>——' +
      '净值跌、赎回、被迫卖出、净值再跌，全程没有人做判断，所以基本面改善也中止不了。',

    '结论：<b>这是一张杠杆拥挤度与浮亏深度的状态快照，不是下跌预测</b>。' + OV.n_flushed +
      ' 只按最激进假设已越过理论追保线，更可能是出清中后段而非风险起点；' +
      '值得逐一看的是解禁日与质押线撞在一起时的<b>多机制同时触发</b>。' +
      '120 日样本检验未发现「距理论线某区间 → 融资盘抢跑 → 加速下跌」的稳定证据，贴线区反而呈缩量与均值反转，' +
      '因此状态标签只描述位置，不代表未来涨跌方向。'
  ];
  document.getElementById('verdict').innerHTML = V.map(function (t) {
    return '<li>' + t + '</li>';
  }).join('');

  /* ---------------- 图表 1：杠杆水位 ---------------- */
  (function drawLever() {
    var g = OV.lever_series || { d: [], rz: [], ratio: [] };
    var opt = {
      animation: false,
      grid: { left: 52, right: 50, top: 30, bottom: 28 },
      tooltip: {
        trigger: 'axis', appendToBody: true,
        backgroundColor: '#111821', borderColor: '#22303f',
        textStyle: { color: '#e9eff7', fontSize: 12 },
        formatter: function (ps) {
          var s = ps[0].axisValue + '<br/>';
          ps.forEach(function (p) {
            s += p.marker + p.seriesName + ' <b>' +
              Number(p.data).toFixed(p.seriesIndex === 0 ? 0 : 2) +
              (p.seriesIndex === 0 ? ' 亿' : '%') + '</b><br/>';
          });
          return s;
        }
      },
      legend: {
        top: 0, right: 0, itemWidth: 10, itemHeight: 8, itemGap: 14,
        textStyle: { color: '#7f8d9f', fontSize: 10.5 }
      },
      xAxis: {
        type: 'category', data: g.d, boundaryGap: false,
        axisLine: { lineStyle: { color: '#22303f' } },
        axisLabel: { color: '#7f8d9f', fontSize: 10, interval: Math.floor(g.d.length / 5) },
        axisTick: { show: false }
      },
      yAxis: [
        {
          type: 'value', name: '融资余额(亿)', nameTextStyle: { color: '#7f8d9f', fontSize: 10 },
          splitLine: { lineStyle: { color: '#1b2634' } },
          axisLabel: { color: '#7f8d9f', fontSize: 10 }
        },
        {
          type: 'value', name: '占比(%)', nameTextStyle: { color: '#7f8d9f', fontSize: 10 },
          splitLine: { show: false }, min: 2, max: 3.4,
          axisLabel: { color: '#7f8d9f', fontSize: 10 }
        }
      ],
      series: [
        {
          name: '融资余额', type: 'line', yAxisIndex: 0, data: g.rz, symbol: 'none',
          lineStyle: { width: 1.8, color: '#4c9aff' },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: 'rgba(76,154,255,.30)' }, { offset: 1, color: 'rgba(76,154,255,.02)' }]
            }
          }
        },
        {
          name: '占流通市值', type: 'line', yAxisIndex: 1, data: g.ratio,
          symbol: 'none', lineStyle: { width: 2, color: '#f0b90b' }
        }
      ]
    };
    CHART('chart-lever', opt);
  })();

  /* ---------------- 图表 2：分布 ---------------- */
  (function drawDist() {
    var vals = S.map(function (o) { return o.ratio; }).filter(function (v) { return !isNaN(v) && v >= 0; });
    var MAXB = 16, step = 1;
    var bins = [], labels = [];
    for (var b = 0; b < MAXB; b++) { bins.push(0); labels.push(b); }
    var over = 0;
    for (var k = 0; k < vals.length; k++) {
      var bi = Math.floor(vals[k] / step);
      if (bi >= MAXB) { over++; } else { bins[bi]++; }
    }
    bins.push(over); labels.push('>' + MAXB);
    var data = bins.map(function (cnt, idx) {
      var col = '#3c4c5f';
      if (idx >= 12) col = '#f6465d';
      else if (idx >= 8) col = '#f0b90b';
      else if (idx >= 5) col = '#7d8dab';
      return { value: cnt, itemStyle: { color: col } };
    });
    var opt = {
      animation: false,
      grid: { left: 46, right: 16, top: 24, bottom: 30 },
      tooltip: {
        trigger: 'axis', appendToBody: true, axisPointer: { type: 'shadow' },
        backgroundColor: '#111821', borderColor: '#22303f',
        textStyle: { color: '#e9eff7', fontSize: 12 },
        formatter: function (p) {
          return '占比 ' + p[0].axisValue + '%<br/>标的数 <b>' + p[0].data.value + '</b> 只';
        }
      },
      xAxis: {
        type: 'category', data: labels,
        axisLine: { lineStyle: { color: '#22303f' } },
        axisLabel: { color: '#7f8d9f', fontSize: 10, interval: 1 },
        axisTick: { show: false }
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#1b2634' } },
        axisLabel: { color: '#7f8d9f', fontSize: 10.5 }
      },
      series: [{ type: 'bar', data: data, barWidth: '72%' }]
    };
    CHART('chart-dist', opt);
  })();

  /* ---------------- 图表 3：各机制触发数量 ---------------- */
  (function drawMech() {
    var rows = [
      { n: '融资追保线在 25% 内', v: S.filter(function (o) { return o.buf_call > 0 && o.buf_call <= 25; }).length, c: '#f6465d' },
      { n: '质押平仓线在 25% 内', v: plNear.length + S.filter(function (o) { return o.pld_room > 15 && o.pld_room <= 25; }).length, c: '#f6465d' },
      { n: '两类强平线共振', v: resList.length, c: '#ff9f43' },
      { n: '60 日解禁 >5% 流通', v: ulkBig.length, c: '#f0b90b' },
      { n: '转债负溢价（套利）', v: S.filter(function (o) { return o.cb_prem < 0; }).length, c: '#f0b90b' },
      { n: '大宗折价出货', v: S.filter(function (o) { return o.blk_disc < -5 && o.blk_ratio > 0.5; }).length, c: '#a06bff' },
      { n: '户数增而价跌', v: S.filter(function (o) { return o.gdhs_dump >= 1; }).length, c: '#4c9aff' },
      { n: '公募占流通 >20%', v: fundCrowd.length, c: '#4c9aff' },
      { n: '大股东净减持 >0.5%', v: S.filter(function (o) { return o.hold_ratio < -0.5; }).length, c: '#4c9aff' }
    ];
    var opt = {
      animation: false,
      grid: { left: 148, right: 60, top: 16, bottom: 24 },
      tooltip: {
        trigger: 'axis', appendToBody: true, axisPointer: { type: 'shadow' },
        backgroundColor: '#111821', borderColor: '#22303f',
        textStyle: { color: '#e9eff7', fontSize: 12 },
        formatter: function (p) {
          return p[0].name + '<br/>命中 <b>' + p[0].data.value + '</b> 只（占全样本 ' +
            fx(p[0].data.value / N * 100, 1) + '%）';
        }
      },
      xAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#1b2634' } },
        axisLabel: { color: '#7f8d9f', fontSize: 10 }
      },
      yAxis: {
        type: 'category', inverse: true,
        data: rows.map(function (r) { return r.n; }),
        axisLine: { lineStyle: { color: '#22303f' } },
        axisLabel: { color: '#a8b6c6', fontSize: 11 },
        axisTick: { show: false }
      },
      series: [{
        type: 'bar', barWidth: '58%',
        data: rows.map(function (r) { return { value: r.v, itemStyle: { color: r.c } }; }),
        label: {
          show: true, position: 'right', color: '#a8b6c6', fontSize: 11,
          formatter: function (p) { return p.data.value; }
        }
      }]
    };
    CHART('chart-mech', opt);
  })();

  /* ---------------- 表格 ---------------- */
  var COLS_M = [
    { k: 'name', t: '标的', l: true, w: 122 },
    { k: 'price', t: '现价', d: 2 },
    { k: 'chg', t: '涨跌%', d: 2, colorCls: true },
    { k: 'fcap', t: '流通市值亿', d: 0 },
    { k: 'rz', t: '融资余额亿', d: 2 },
    { k: 'ratio', t: '占流通市值%', d: 2, strong: true, w: 96 },
    { k: 'dratio20', t: '20日Δpp', d: 2, risk: true, w: 76 },
    { k: 'pnl', t: '浮盈亏%', d: 1, colorCls: true },
    { k: 'buf_call', t: '距追保线%', d: 1, buf: true, w: 84 },
    { k: 'pos120', t: '距高点%', d: 1, colorCls: true, w: 76 },
    { k: 'res_cnt', t: '共振', d: 0, res: true, w: 58 },
    { k: 'score', t: '压力分', d: 1, score: 'score' },
    { k: 'frag', t: '脆弱度', d: 1, score: 'frag' },
    { k: 'state', t: '状态' },
    { k: 'level', t: '分级' },
    { k: 'tags', t: '标签', l: true, tags: true, w: 150 }
  ];

  var COLS_S = [
    { k: 'name', t: '标的', l: true, w: 122 },
    { k: 'price', t: '现价', d: 2 },
    { k: 'chg', t: '涨跌%', d: 2, colorCls: true },
    { k: 'fcap', t: '流通市值亿', d: 0 },
    { k: 'pld_ratio', t: '质押比例%', d: 1, w: 80 },
    { k: 'pld_room', t: '距质押平仓%', d: 1, room: true, w: 98 },
    { k: 'ulk60', t: '60日解禁%', d: 1, hot: true, w: 88 },
    { k: 'cb_prem', t: '转债溢价%', d: 0, w: 86 },
    { k: 'blk_ratio', t: '大宗占比%', d: 2, w: 86 },
    { k: 'blk_disc', t: '大宗折价%', d: 1, colorCls: true, w: 86 },
    { k: 'gdhs_chg', t: '户数变化%', d: 1, colorCls: true, w: 88 },
    { k: 'fund_pct', t: '公募占流通%', d: 1, w: 96 },
    { k: 'bb_prem', t: '回购价空间%', d: 0, w: 96 },
    { k: 'res_cnt', t: '共振', d: 0, res: true, w: 58 },
    { k: 'res_score', t: '结构分', d: 1, score: 'res', w: 78 },
    { k: 'level', t: '分级' },
    { k: 'res_ev_tag', t: '事件', l: true, evt: true, w: 140 }
  ];

  var COLS = COLS_M, viewMode = 'margin';
  var sortKey = 'score', sortDir = -1, page = 0, PS = 50;
  var SRC = S.slice();   /* 原始顺序的不可变副本：行上的 data-i 存的是这里的下标 */
  var view = S.slice();  /* 展示序列，排序与筛选只作用在它身上，绝不回写 SRC */
  var RISK_TAGS = { '价跌加杠杆': 1, '临界': 1, '占比畸高': 1, '高位加杠杆': 1 };

  function renderHead() {
    document.getElementById('thead').innerHTML = COLS.map(function (c) {
      return '<th data-k="' + c.k + '" class="' + (c.l ? 'l' : '') + '" style="min-width:' + (c.w || 64) + 'px">' +
        c.t + '<span class="ar" id="ar-' + c.k + '"></span></th>';
    }).join('');
  }
  renderHead();

  function applySort() {
    var k = sortKey, dir = sortDir;
    view.sort(function (a, b) {
      var x = a[k], y = b[k];
      if (k === 'name' || k === 'level' || k === 'tags' || k === 'code' || k === 'state') {
        x = String(x); y = String(y);
        return x < y ? -dir : (x > y ? dir : 0);
      }
      x = (x === null || isNaN(x)) ? -1e9 : Number(x);
      y = (y === null || isNaN(y)) ? -1e9 : Number(y);
      return (x - y) * dir;
    });
  }

  function stateColor(s) {
    if (s === '临界') return '#f6465d';
    if (s === '潜伏') return '#f0b90b';
    if (s === '已去杠杆') return '#8b6dff';
    if (s === '安全') return '#5d7186';
    return '#5d7186';
  }

  function rowHTML(o) {
    var lvCls = o.level === '高危' ? 'hi' : (o.level === '关注' ? 'wa' : '');
    var bd = o.level === '高危' ? 'h' : (o.level === '关注' ? 'w' : 'n');
    var cells = COLS.map(function (c) {
      if (c.k === 'name') {
        return '<td class="l"><span class="nm">' + esc(o.name) + '</span><span class="cd mono">' + o.code + '</span></td>';
      }
      if (c.k === 'level') {
        return '<td><span class="badge ' + bd + '">' + o.level + '</span></td>';
      }
      if (c.k === 'state') {
        return '<td style="color:' + stateColor(o.state) + ';font-weight:600;font-size:11.5px">' + o.state + '</td>';
      }
      if (c.tags) {
        var ts = (o.tags || '').split('|').filter(Boolean).slice(0, 2);
        return '<td class="l" style="max-width:190px;overflow:hidden;text-overflow:ellipsis">' + ts.map(function (t) {
          return '<span class="tg' + (RISK_TAGS[t] ? ' risk' : '') + '">' + t + '</span>';
        }).join('') + '</td>';
      }
      if (c.evt) {
        var es = (o[c.k] || '').split('|').filter(Boolean).slice(0, 2);
        if (!es.length) return '<td class="l dim">—</td>';
        return '<td class="l" style="max-width:170px;overflow:hidden;text-overflow:ellipsis">' + es.map(function (t) {
          return '<span class="tg risk">' + t + '</span>';
        }).join('') + '</td>';
      }
      if (c.res) {
        var rc = o[c.k] || 0;
        var rcol = rc >= 2 ? '#f6465d' : (rc >= 1 ? '#f0b90b' : '#3d4b5c');
        var rtxt = rc >= 2 ? '×2' : (rc >= 1 ? '×1' : '—');
        return '<td style="color:' + rcol + ';font-weight:700;font-size:11.5px">' + rtxt + '</td>';
      }
      if (c.room) {
        var rv = o[c.k];
        if (rv === null || rv === undefined || isNaN(rv)) return '<td class="dim">—</td>';
        var rvc = rv < 0 ? '#8b6dff' : (rv < 15 ? '#f6465d' : (rv < 30 ? '#f0b90b' : ''));
        return '<td style="' + (rvc ? 'color:' + rvc + ';font-weight:600' : '') + '">' + fx(rv, 1) + '</td>';
      }
      if (c.hot) {
        var hv = o[c.k];
        if (hv === null || hv === undefined || isNaN(hv) || hv < 0.01) return '<td class="dim">—</td>';
        var hvc = hv >= 5 ? '#f6465d' : (hv >= 2 ? '#f0b90b' : '');
        return '<td style="' + (hvc ? 'color:' + hvc + ';font-weight:600' : '') + '">' + fx(hv, 1) + '</td>';
      }
      if (c.score) {
        var sc = o[c.k] || 0;
        var pctv = c.score === 'res' ? sc / 3 * 100 : sc;
        var col = sc >= 85 ? '#f6465d' : (sc >= 70 ? '#f0b90b' : '#4c6785');
        if (c.score === 'frag') { col = sc >= 88 ? '#a06bff' : (sc >= 75 ? '#8b6dff' : '#4c6785'); }
        if (c.score === 'res') { col = sc >= 2.5 ? '#f6465d' : (sc >= 1.5 ? '#f0b90b' : '#4c6785'); }
        return '<td><span class="mini"><span class="bar"><i style="width:' + Math.min(100, pctv) + '%;background:' + col + '"></i></span>' +
          '<span style="color:' + col + ';font-weight:600">' + fx(sc, 1) + '</span></span></td>';
      }
      if (c.buf) {
        var bc = o.buf_call;
        var bcol = bc < 0 ? '#8b6dff' : (bc < 15 ? '#f6465d' : (bc < 25 ? '#f0b90b' : ''));
        return '<td style="' + (bcol ? 'color:' + bcol + ';font-weight:600' : '') + '">' + fx(bc, 1) + '</td>';
      }
      if (c.risk) {
        var v = o[c.k];
        var rcol = v > 0 ? '#f0b90b' : '#5d7186';
        return '<td style="color:' + rcol + '">' + sgn(v, c.d) + '</td>';
      }
      var val = o[c.k];
      var klass = c.colorCls ? cls(val) : '';
      var style = c.strong ? 'font-weight:700' : '';
      return '<td class="' + klass + '" style="' + style + '">' + (c.d !== undefined ? fx(val, c.d) : (val || '—')) + '</td>';
    }).join('');
    return '<tr class="' + lvCls + '" data-i="' + o._i + '">' + cells + '</tr>';
  }

  function render() {
    var total = view.length;
    var pages = Math.max(1, Math.ceil(total / PS));
    if (page >= pages) page = pages - 1;
    if (page < 0) page = 0;
    var start = page * PS;
    var slice = view.slice(start, start + PS);
    document.getElementById('tbody').innerHTML = slice.map(rowHTML).join('') ||
      '<tr><td colspan="' + COLS.length + '" style="padding:30px;text-align:center;color:#7f8d9f">没有符合条件的标的</td></tr>';
    document.getElementById('hit').textContent = total.toLocaleString('en-US');
    document.getElementById('pgInfo').textContent =
      '第 ' + (total ? start + 1 : 0) + '–' + Math.min(start + PS, total) + ' 条，共 ' + total.toLocaleString('en-US') + ' 条';
    document.getElementById('pgNum').textContent = (page + 1) + ' / ' + pages;
    document.getElementById('prev').disabled = page <= 0;
    document.getElementById('next').disabled = page >= pages - 1;
    COLS.forEach(function (c) {
      var el = document.getElementById('ar-' + c.k);
      if (el) el.textContent = (c.k === sortKey) ? (sortDir > 0 ? '▲' : '▼') : '';
    });
  }

  document.getElementById('thead').addEventListener('click', function (e) {
    var th = e.target.closest('th');
    if (!th) return;
    var k = th.getAttribute('data-k');
    if (sortKey === k) { sortDir = -sortDir; }
    else {
      sortKey = k;
      sortDir = (k === 'name' || k === 'level' || k === 'tags' || k === 'state') ? 1 : -1;
    }
    page = 0;
    applySort();
    render();
    updateHint();
  });

  /* ---------------- 筛选 ---------------- */
  var fLevel = 'all', fTag = '', fState = '', fQ = '', fMech = '';
  var nz = function (v) { return v !== null && v !== undefined && !isNaN(v); };

  function mechHit(o) {
    switch (fMech) {
      case 'res2': return (o.res_cnt || 0) >= 2;
      case 'pledge': return nz(o.pld_room) && o.pld_room > 0 && o.pld_room <= 15;
      case 'unlock': return nz(o.ulk60) && o.ulk60 >= 5;
      case 'cb': return nz(o.cb_prem) && o.cb_prem < 0;
      case 'block': return nz(o.blk_disc) && o.blk_disc < -5 && o.blk_ratio > 0.5;
      case 'dump': return (o.gdhs_dump || 0) >= 1;
      case 'fund': return nz(o.fund_pct) && o.fund_pct > 20;
      case 'hold': return nz(o.hold_ratio) && o.hold_ratio < -0.5;
      case 'buyback': return nz(o.bb_prem) && o.bb_prem > 30;
      default: return true;
    }
  }

  function refilter() {
    view = S.filter(function (o) {
      if (fLevel !== 'all' && o.level !== fLevel) return false;
      if (fState && o.state !== fState) return false;
      if (fTag && (!o.tags || o.tags.indexOf(fTag) < 0)) return false;
      if (fMech && !mechHit(o)) return false;
      if (fQ && o._k.toLowerCase().indexOf(fQ) < 0) return false;
      return true;
    });
    page = 0;
    applySort();
    render();
  }

  document.getElementById('segLevel').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    Array.prototype.forEach.call(this.querySelectorAll('button'), function (x) { x.classList.remove('on'); });
    b.classList.add('on');
    fLevel = b.getAttribute('data-lv');
    refilter();
  });

  function updateHint() {
    var el = document.getElementById('hint');
    if (!el) return;
    if (sortKey === 'res_score') {
      el.innerHTML = '当前按<b>结构共振分</b>排序：<code>价格强平线共振数 + 事件型卖出</code>。' +
        '前排是融资盘与质押两类强平线都落在现价下方 25% 以内的标的——再跌一段，卖压来自两套互不相干的账户，' +
        '而不是同一种情绪。这一类是本版新加的最有效筛子，全市场只有 <b>' + resList.length + '</b> 只。';
    } else if (sortKey === 'frag') {
      el.innerHTML = '当前按<b>前瞻脆弱度</b>排序：前排是杠杆已堆高、但浮亏尚未展开的标的。它们距理论追保线大多还很远、压力分不高，' +
        '但估算成本线已经贴近现价。这是拥挤度读数，不构成下跌预测。';
    } else if (sortKey === 'score') {
      el.innerHTML = '当前按<b>已实现压力</b>排序：前排多是已经跌透、融资盘被强平过一轮的标的，因此分级多为「关注」而非「高危」。' +
        '要看浮亏逼近理论线且压力分高的名单，点上面的「高危」；要看杠杆仍在堆高的，切到「前瞻脆弱度」。' +
        '分级是排序规则，不是风险预测。';
    } else if (sortKey === 'pld_room' || sortKey === 'ulk60' || sortKey === 'fund_pct') {
      el.innerHTML = '按「' + sortKey + '」排序。注意方向：<b>距质押平仓线</b>越小越危险；' +
        '<b>60 日解禁</b>占流通市值越高，供给侧冲击越大（次新股常见 100% 以上）；' +
        '<b>公募占流通</b>越高，越依赖基金申购的持续性而不是基本面。';
    } else {
      el.innerHTML = '按「' + sortKey + '」排序。三档分级只从「临界」状态里产生（排序规则，非下跌预警），已去杠杆的标的不会被列进高危。';
    }
  }

  document.getElementById('segSort').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    Array.prototype.forEach.call(this.querySelectorAll('button'), function (x) { x.classList.remove('on'); });
    b.classList.add('on');
    var sk = b.getAttribute('data-sk');
    sortKey = sk; sortDir = -1; page = 0;
    applySort(); render(); updateHint();
  });

  document.getElementById('selState').addEventListener('change', function () { fState = this.value; refilter(); });
  document.getElementById('selTag').addEventListener('change', function () { fTag = this.value; refilter(); });
  document.getElementById('selMech').addEventListener('change', function () { fMech = this.value; refilter(); });

  document.getElementById('segView').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    Array.prototype.forEach.call(this.querySelectorAll('button'), function (x) { x.classList.remove('on'); });
    b.classList.add('on');
    viewMode = b.getAttribute('data-vw');
    COLS = viewMode === 'margin' ? COLS_M : COLS_S;
    sortKey = viewMode === 'margin' ? 'score' : 'res_score';
    sortDir = -1; page = 0;
    renderHead(); applySort(); render(); updateHint();
  });
  var qt = null;
  document.getElementById('q').addEventListener('input', function () {
    var v = this.value.trim().toLowerCase();
    clearTimeout(qt);
    qt = setTimeout(function () { fQ = v; refilter(); }, 120);
  });
  document.getElementById('prev').addEventListener('click', function () { page--; render(); });
  document.getElementById('next').addEventListener('click', function () { page++; render(); });

  document.getElementById('ct-all').textContent = N;
  document.getElementById('ct-h').textContent = hiList.length;
  document.getElementById('ct-w').textContent = waList.length;
  document.getElementById('ct-n').textContent = N - hiList.length - waList.length;

  /* ---------------- 详情抽屉 ---------------- */
  var drawer = document.getElementById('drawer');
  var mask = document.getElementById('mask');

  function dimBar(label, v, col) {
    v = v || 0;
    return '<div class="dimbar"><span class="k">' + label + '</span>' +
      '<span class="track"><i style="width:' + Math.min(100, v) + '%;background:' + col + '"></i></span>' +
      '<span class="v">' + fx(v, 0) + '</span></div>';
  }

  function describe(o) {
    var out = [];
    if (o.state === '已去杠杆') {
      out.push('<b>状态描述：按最激进假设，融资盘浮亏已越过理论平仓线。</b>估算成本 ' + fx(o.cost, 2) +
        ' 元、现价 ' + fx(o.price, 2) + '，融资盘浮亏 ' + fx(-o.pnl, 1) + '%。' +
        '这意味着存量余额里被强平的部分大概率已经消失，现在的余额是洗牌后的残余加上新进的抄底盘。' +
        '<b>把它当「即将爆仓」是读错了方向</b>——它更可能是出清中后段；后续变化取决于新进仓位的成本分布与成交状态。');
    } else if (o.state === '临界') {
      out.push('<b>状态描述：融资盘浮亏接近按最激进假设推出的理论追保线。</b>估算成本 ' + fx(o.cost, 2) + ' 元、现价 ' + fx(o.price, 2) +
        '，融资盘浮亏 ' + fx(-o.pnl, 1) + '%。按 80% 保证金满仓假设反推，股价再跌 <b>' + fx(o.buf_call, 1) +
        '%</b> 才触及理论 150% 追保线，距理论 130% 平仓线还有 ' + fx(o.buf_liq, 1) + '%。' +
        '这两条线只对应满仓 80% 保证金的极端账户，全市场平均维持担保比例在 250% 以上，<b>不代表真实强平阈值</b>。' +
        '120 日样本检验没有发现「贴线 → 主动卸杠杆 → 加速下跌」的稳定证据，贴线区反而多为缩量与均值反转；' +
        '因此这一档应读作浮亏深度与杠杆拥挤度的位置，<b>不是下跌预警</b>。');
    } else if (o.state === '潜伏') {
      out.push('<b>状态描述：杠杆拥挤度处在抬升中，浮亏尚未展开。</b>融资余额占流通市值 ' +
        fx(o.ratio, 2) + '%（全市场 ' + fx(o.pct_crowd, 0) + ' 分位），20 日又抬升 ' + fx(o.dratio20, 2) +
        ' 个百分点。当前浮盈亏 ' + sgn(o.pnl, 1) + '%，距理论追保线还有 ' + fx(o.buf_call, 1) + '%。' +
        '成本线已被推到接近现价的位置，浮盈对回调的缓冲有限；但这是拥挤度读数，<b>不构成下跌预测</b>。');
    } else {
      out.push('当前处于中性区间：占比 ' + fx(o.ratio, 2) + '%（全市场 ' + fx(o.pct_crowd, 0) + ' 分位），' +
        '浮亏 ' + fx(o.pnl, 1) + '%，距追保线 ' + fx(o.buf_call, 1) + '%，20 日增仓 ' + sgn(o.dratio20, 2) + 'pp。' +
        '没有明显的杠杆脆弱特征，列在这里主要是为了给出全市场坐标系。');
    }
    if (o.tags && o.tags.indexOf('价跌加杠杆') >= 0) {
      out.push('<b>注意股价与杠杆的背离：</b>近 20 日股价 ' + sgn(o.ret20, 1) + '%，融资余额却逆势 ' + sgn(o.rz_chg20, 1) +
        '%。抄底加杠杆的仓位会在横盘中不断累积浮亏，不需要新的利空就能触发减仓。');
    }
    if (o.buy_share5 > 14) {
      out.push('近 5 日融资买入额占成交额 <b>' + fx(o.buy_share5, 1) + '%</b>，边际定价权很大程度落在杠杆资金手里，涨跌都会被放大。');
    }
    if (o.rz_days > 8) {
      out.push('融资余额相当于 <b>' + fx(o.rz_days, 1) + '</b> 天的成交额，沉淀较厚。一旦进入去杠杆，抛压持续的时间会明显长于平均水平。');
    }

    /* ---- 持仓结构层 ---- */
    if (nz(o.pld_room)) {
      if (o.pld_room < 0) {
        out.push('<b>质押盘已经跌穿预估平仓线。</b>加权平仓线约 ' + fx(o.pld_line, 2) + ' 元，现价 ' + fx(o.price, 2) +
          ' 元已在其下方。质押比例 ' + fx(o.pld_ratio, 1) + '%、' + fx(o.pld_n, 0) + ' 笔。' +
          '这类股权要么已被券商处置过，要么靠补充质押、追加保证金硬撑——两种情况下，' +
          '<b>大股东的流动性都是紧的</b>，稍有利空更容易演变成被动减持。');
      } else if (o.pld_room <= 15) {
        out.push('<b>质押盘就在平仓线门口：</b>加权平仓线 ' + fx(o.pld_line, 2) + ' 元，现价再跌 <b>' + fx(o.pld_room, 1) +
          '%</b> 就到了。质押比例 ' + fx(o.pld_ratio, 1) + '%。质押强平与融资强平的区别在于节奏——' +
          '券商处置不会在盘口一次性砸出，而是走大宗、协议转让或司法拍卖，<b>对股价是持续几个月的压制，而不是一天的暴跌</b>。' +
          '这种压力最容易被误判为"阴跌找不到原因"。');
      } else if (o.pld_room <= 30) {
        out.push('质押平仓线在现价下方 ' + fx(o.pld_room, 1) + '%（' + fx(o.pld_line, 2) + ' 元），质押比例 ' +
          fx(o.pld_ratio, 1) + '%。缓冲不算厚，属于需要记在备查清单里的那一类。');
      }
    }
    if (nz(o.ulk60) && o.ulk60 >= 2) {
      out.push('<b>未来 60 日有解禁：</b>解禁市值相当于当前流通市值的 <b>' + fx(o.ulk60, 1) + '%</b>' +
        (nz(o.ulk_next) ? '，最近一次在 <b>' + fx(o.ulk_next, 0) + ' 天后</b>' : '') + '。' +
        '解禁不等于减持，但它是<b>唯一可以提前精确排期的供给冲击</b>——其他机制都是概率，解禁是日历。' +
        '占比超过 50% 的多为首发原股东解禁，这类筹码的成本极低，任何价格卖出都是盈利。');
    }
    if (nz(o.cb_prem) && o.cb_prem < 3) {
      out.push('<b>转债转股压力：</b>转股溢价率 ' + sx(o.cb_prem) + '%，转股价 ' + fx(o.cb_conv, 2) + ' 元。' +
        (o.cb_prem < 0
          ? '负溢价意味着<b>转股后立即卖出是无风险套利</b>，这个卖压是机械执行的，不依赖任何人的判断。'
          : '溢价接近零，转股套利随时会被激活。') +
        (nz(o.cb_force_up) && o.cb_force_up > 0 && o.cb_force_up <= 8
          ? ' 且距强赎触发价只剩 ' + fx(o.cb_force_up, 1) + '%，一旦触发强赎，剩余转债会被强制转股，形成集中抛压。' : ''));
    }
    if (nz(o.fund_pct) && o.fund_pct > 15) {
      out.push('<b>公募持仓拥挤：</b>' + fx(o.fund_n, 0) + ' 只基金持有，占流通股 <b>' + fx(o.fund_pct, 1) + '%</b>。' +
        '这一条的危险不在"基金经理看空"，而在<b>赎回机制</b>——净值下跌引发赎回，基金被迫卖出，卖出又压低净值。' +
        '整个过程没有人做判断，所以也无法通过基本面改善来中止。近 20 日股价 ' + sx(o.ret20) + '%。');
    }
    if (nz(o.gdhs_chg) && o.gdhs_chg > 3 && o.ret20 < 0) {
      out.push('<b>筹码在分散：</b>股东户数增加 ' + fx(o.gdhs_chg, 1) + '%，同期股价 ' + sx(o.ret20) + '%。' +
        '户数增而价跌，是<b>主力派发、散户接盘</b>的标准形态。这个指标的好处是不受杠杆规则变化干扰，' +
        '看到的就是筹码在谁手里。');
    }
    if (nz(o.blk_disc) && o.blk_disc < -5 && o.blk_ratio > 0.5) {
      out.push('<b>有大宗折价出货：</b>近 30 日大宗成交占流通市值 ' + fx(o.blk_ratio, 2) + '%，加权折价 ' +
        fx(o.blk_disc, 1) + '%。折价接盘方通常是短线资金，<b>接过来就是为了在二级市场卖掉</b>，' +
        '所以这批筹码只是延后了卖压，没有消失。');
    }
    if (nz(o.hold_ratio) && o.hold_ratio < -0.5) {
      out.push('近 120 日重要股东<b>净减持</b> ' + fx(-o.hold_ratio, 2) + '% 流通市值。产业资本在这个价位选择卖出，是一个不该忽略的相对估值信号。');
    }
    if (nz(o.bb_prem) && o.bb_prem > 30) {
      out.push('<b>有回购计划托底：</b>回购价格上限比现价高 <b>' + fx(o.bb_prem, 0) + '%</b>。' +
        '这是名单里少见的<b>承接力量</b>——回购价上限构成显性买盘价位，也等于管理层对内在价值的自我定价。' +
        '但要注意计划可能已公告很久、执行比例才是关键。');
    }
    if ((o.res_cnt || 0) >= 2) {
      out.push('<b>两类强平线共振。</b>融资盘追保线在下方 ' + fx(o.buf_call, 1) + '%、质押平仓线在下方 ' +
        fx(o.pld_room, 1) + '%，两条线挤在同一段跌幅里。这意味着再跌一段，卖压来自两套完全独立、' +
        '彼此不知道对方存在的账户：<b>融资客被通知减仓，质押股东被券商处置</b>。' +
        '这不是情绪问题，是合同问题。');
    }
    return out.join('<br><br>');
  }

  function openOf(o) {
    document.getElementById('dname').innerHTML =
      esc(o.name) + '<span class="badge ' + (o.level === '高危' ? 'h' : o.level === '关注' ? 'w' : 'n') + '">' + o.level + '</span>' +
      '<span style="font-size:11.5px;font-weight:600;color:' + stateColor(o.state) + '">' + o.state + '</span>';

    var chgCls = o.chg > 0 ? 'pos' : (o.chg < 0 ? 'neg' : 'dim');
    document.getElementById('dsub').innerHTML =
      '<span class="mono">' + o.code + '</span>' +
      '<span>现价 <b class="' + chgCls + '">' + fx(o.price, 2) + '</b> <span class="' + chgCls + '">' + sgn(o.chg, 2) + '%</span></span>' +
      '<span>流通市值 <b>' + fx(o.fcap, 0) + '</b> 亿</span>' +
      '<span>融资余额 <b>' + fx(o.rz, 2) + '</b> 亿</span>';

    var tagHtml = (o.tags || '').split('|').filter(Boolean).map(function (t) {
      return '<span class="tg' + (RISK_TAGS[t] ? ' risk' : '') + '">' + t + '</span>';
    }).join('');

    var bufCol = o.buf_call < 0 ? '#8b6dff' : (o.buf_call < 15 ? '#f6465d' : (o.buf_call < 25 ? '#f0b90b' : '#0ecb81'));

    var KPI2 = [
      ['融资余额占流通市值', fx(o.ratio, 2) + '%', o.ratio > 8 ? '#f6465d' : (o.ratio > 5 ? '#f0b90b' : '')],
      ['20 日占比变化', sgn(o.dratio20, 2) + ' pp', o.dratio20 > 0 ? '#f0b90b' : '#5d7186'],
      ['5 日余额变化', sgn(o.rz_chg5, 1) + '%', o.rz_chg5 > 0 ? '#f0b90b' : '#5d7186'],
      ['20 日余额变化', sgn(o.rz_chg20, 1) + '%', o.rz_chg20 > 0 ? '#f0b90b' : '#5d7186'],
      ['估算建仓成本', fx(o.cost, 2), ''],
      ['融资盘浮盈亏', sgn(o.pnl, 1) + '%', o.pnl < 0 ? '#0ecb81' : '#f6465d'],
      ['距追保线剩余跌幅', fx(o.buf_call, 1) + '%', bufCol],
      ['距平仓线剩余跌幅', fx(o.buf_liq, 1) + '%', o.buf_liq < 15 ? '#f6465d' : ''],
      ['距 120 日高点', sgn(o.pos120, 1) + '%', o.pos120 > -3 ? '#f0b90b' : '#5d7186'],
      ['20 日涨跌', sgn(o.ret20, 1) + '%', o.ret20 > 0 ? '#f6465d' : '#0ecb81'],
      ['5 日融资买入占成交', fx(o.buy_share5, 1) + '%', o.buy_share5 > 14 ? '#f0b90b' : ''],
      ['杠杆沉淀天数', fx(o.rz_days, 1) + ' 天', o.rz_days > 8 ? '#f0b90b' : ''],
      ['融券余额', fx(o.rq, 2) + ' 亿', ''],
      ['压力分 / 脆弱度', fx(o.score, 1) + ' / ' + fx(o.frag, 1), '']
    ];

    /* 动态风险维度：与静态成本线并列，避免把「位置」读成「预测」 */
    var DYN = [
      ['20 日波动率分位', fx(o.vol_pct, 0) + ' 分位',
        o.vol_pct >= 80 ? '#f6465d' : (o.vol_pct >= 60 ? '#f0b90b' : '')],
      ['20 日波动率（日）', fx(o.vol20, 2) + '%', ''],
      ['当日成交额 / 20 日均额', fx(o.amt_vr, 2) + '×',
        o.amt_vr >= 1.5 ? '#f0b90b' : (o.amt_vr <= 0.7 ? '#8b9fb3' : '')]
    ];

    /* 持仓结构指标（有数据才出现） */
    var KPI3 = [];
    if (nz(o.pld_line)) {
      KPI3.push(['质押比例 / 笔数', fx(o.pld_ratio, 1) + '% / ' + fx(o.pld_n, 0) + ' 笔',
        o.pld_ratio > 30 ? '#f6465d' : '']);
      KPI3.push(['加权预估平仓线', fx(o.pld_line, 2) + ' 元', '']);
      KPI3.push(['距质押平仓线', fx(o.pld_room, 1) + '%',
        o.pld_room < 0 ? '#8b6dff' : (o.pld_room < 15 ? '#f6465d' : (o.pld_room < 30 ? '#f0b90b' : ''))]);
      if (nz(o.pld_maxline)) KPI3.push(['最高一笔平仓线', fx(o.pld_maxline, 2) + ' 元', '']);
    }
    if (nz(o.ulk120)) {
      KPI3.push(['未来 60 日解禁', fx(o.ulk60, 1) + '% 流通市值',
        o.ulk60 >= 5 ? '#f6465d' : (o.ulk60 >= 2 ? '#f0b90b' : '')]);
      KPI3.push(['未来 120 日解禁', fx(o.ulk120, 1) + '%', '']);
      if (nz(o.ulk_next)) KPI3.push(['距下次解禁', fx(o.ulk_next, 0) + ' 天', '']);
    }
    if (nz(o.cb_conv)) {
      KPI3.push(['转股溢价率', fx(o.cb_prem, 1) + '%', o.cb_prem < 0 ? '#f6465d' : '']);
      KPI3.push(['转股价 / 距离', fx(o.cb_conv, 2) + ' 元 / ' + fx(o.cb_room, 1) + '%', '']);
      if (nz(o.cb_force_up)) KPI3.push(['距强赎触发', fx(o.cb_force_up, 1) + '%',
        o.cb_force_up > 0 && o.cb_force_up <= 8 ? '#f6465d' : '']);
    }
    if (nz(o.blk_ratio) && o.blk_ratio > 0) {
      KPI3.push(['近 30 日大宗占比', fx(o.blk_ratio, 2) + '% 流通市值', o.blk_ratio > 1 ? '#f0b90b' : '']);
      KPI3.push(['大宗加权折价', sx(o.blk_disc) + '%', o.blk_disc < -5 ? '#f6465d' : '']);
      KPI3.push(['大宗笔数', fx(o.blk_n, 0) + ' 笔', '']);
    }
    if (nz(o.gdhs_chg)) {
      KPI3.push(['股东户数变化', sx(o.gdhs_chg) + '%',
        (o.gdhs_chg > 0 && o.ret20 < 0) ? '#f6465d' : '']);
      KPI3.push(['户均持股市值', fx((o.gdhs_avg_mv || 0) / 1e4, 1) + ' 万元', '']);
    }
    if (nz(o.fund_pct)) {
      KPI3.push(['公募占流通股', fx(o.fund_pct, 1) + '%', o.fund_pct > 20 ? '#f0b90b' : '']);
      KPI3.push(['持有基金家数', fx(o.fund_n, 0) + ' 家', '']);
    }
    if (nz(o.bb_prem)) {
      KPI3.push(['回购价上限空间', sx(o.bb_prem) + '%', '']);
    }
    if (nz(o.hold_ratio)) {
      KPI3.push(['120 日大股东净变动', sx(o.hold_ratio) + '% 流通市值',
        o.hold_ratio < 0 ? '#0ecb81' : '#f6465d']);
    }

    /* 成本线位置：同一根价格轴上的所有触发线 */
    var LINE_DEF = [
      { n: '融资追保线', v: o.buf_call, c: '#f6465d', px: o.price * (1 - (o.buf_call || 0) / 100) },
      { n: '融资平仓线', v: o.buf_liq, c: '#c0392b', px: o.price * (1 - (o.buf_liq || 0) / 100) },
      { n: '质押平仓线', v: o.pld_room, c: '#ff9f43', px: o.pld_line },
      { n: '转债转股价', v: o.cb_room, c: '#4c9aff', px: o.cb_conv }
    ].filter(function (x) { return nz(x.v) && nz(x.px); });

    var lineHtml = LINE_DEF.sort(function (a, b) { return a.v - b.v; }).map(function (x) {
      var v = x.v;                       // v = 现价再跌多少触及
      var rel = -v;                      // 该线相对现价的位置（负=在下方）
      var col = v < 0 ? '#8b6dff' : (v <= 15 ? '#f6465d' : (v <= 25 ? '#f0b90b' : '#5d7186'));
      var tag = v < 0 ? '已跌破' : (v <= 15 ? '贴线' : (v <= 25 ? '接近' : '安全'));
      return '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px dashed rgba(34,48,63,.7);font-size:12.5px">' +
        '<span style="width:7px;height:7px;border-radius:50%;background:' + col + ';flex:none"></span>' +
        '<span style="width:76px;color:var(--muted);flex:none">' + x.n + '</span>' +
        '<span style="width:62px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums">' + fx(x.px, 2) + '</span>' +
        '<span style="width:66px;text-align:right;color:' + col + ';font-weight:600;font-variant-numeric:tabular-nums">' + sgn(rel, 1) + '%</span>' +
        '<span style="flex:1;text-align:right;color:' + col + ';font-size:11px">' + tag + '</span>' +
        '</div>';
    }).join('');
    var resNote = (o.res_detail || '').split('|').filter(Boolean).length >= 2
      ? '<div style="margin-top:10px;padding-top:9px;border-top:1px solid var(--rule);font-size:11.5px;color:#ff8f9e">' +
        '<b>两类强平线共振：</b>再跌一段，卖压来自两套互不相干的账户——融资盘触线减仓，质押盘被券商处置。</div>'
      : '';

    document.getElementById('dbody').innerHTML =
      '<div class="card">' +
        '<h3>因子构成（全市场百分位）</h3>' +
        dimBar('拥挤度', o.pct_crowd, '#f6465d') +
        dimBar('加杠杆速度', o.pct_speed, '#f0b90b') +
        dimBar('浮亏深度', o.pct_loss, '#a06bff') +
        dimBar('价格位置', o.pct_pos, '#4c9aff') +
        '<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--rule);display:flex;justify-content:space-between;align-items:baseline">' +
          '<span style="font-size:12px;color:var(--muted)">已实现压力 / 前瞻脆弱度</span>' +
          '<span style="font-size:18px;font-weight:700">' +
            '<span style="color:' + (o.score >= 85 ? '#f6465d' : o.score >= 70 ? '#f0b90b' : '#8b9fb3') + '">' + fx(o.score, 1) + '</span>' +
            '<span style="color:#3d4b5c"> / </span>' +
            '<span style="color:' + (o.frag >= 88 ? '#a06bff' : o.frag >= 75 ? '#8b6dff' : '#8b9fb3') + '">' + fx(o.frag, 1) + '</span>' +
          '</span>' +
        '</div>' +
        (tagHtml ? '<div style="margin-top:10px">' + tagHtml + '</div>' : '') +
      '</div>' +

      '<div class="card"><h3>动态风险维度</h3><div class="grid2" style="grid-template-columns:1fr;gap:2px">' +
        DYN.map(function (r) {
          return '<div class="mrow"><span class="k">' + r[0] + '</span><span class="v" style="' +
            (r[2] ? 'color:' + r[2] : '') + '">' + r[1] + '</span></div>';
        }).join('') +
        '</div>' +
        '<div style="margin-top:9px;font-size:11px;color:#5f6f81;line-height:1.65">' +
        '静态成本线只说明杠杆压在哪个价位。经验检验里，未来 5 日快速下跌的主导变量是波动率与成交状态，' +
        '而不是距理论线的距离；这一组是描述性坐标，不能单独当作预警或买卖信号。' +
        '</div></div>' +

      '<div class="card">' +
        '<h3>融资余额 vs 股价（近 ' + HD.length + ' 交易日）</h3>' +
        '<div id="chart-stock" style="width:100%;height:285px"></div>' +
        (LINE_DEF.length ? '<div style="margin-top:8px;font-size:11px;color:#5f6f81">亮红虚线＝融资追保线，浅红细虚线＝融资平仓线，两线之间的浅红带是追保后到强平的缓冲区间；橙色虚线＝质押平仓线，蓝色虚线＝转股价。落在视野之外的线见下方「成本线位置」。</div>' : '') +
      '</div>' +

      (LINE_DEF.length ? '<div class="card"><h3>成本线位置（现价 ' + fx(o.price, 2) + ' 元）</h3>' +
        lineHtml + resNote + '</div>' : '') +

      '<div class="card"><h3>指标明细</h3><div class="grid2">' +
        KPI2.map(function (r) {
          return '<div class="mrow"><span class="k">' + r[0] + '</span><span class="v" style="' + (r[2] ? 'color:' + r[2] : '') + '">' + r[1] + '</span></div>';
        }).join('') +
      '</div></div>' +

      (KPI3.length ? '<div class="card"><h3>持仓结构</h3><div class="grid2">' +
        KPI3.map(function (r) {
          return '<div class="mrow"><span class="k">' + r[0] + '</span><span class="v" style="' + (r[2] ? 'color:' + r[2] : '') + '">' + r[1] + '</span></div>';
        }).join('') + '</div></div>' : '') +

      '<div class="card"><h3>读法</h3><div class="note">' + describe(o) + '</div></div>';

    drawer.classList.add('on');
    mask.classList.add('on');
    drawStock(o);
  }

  function drawStock(o) {
    var h = (P.hist || {})[o.code];
    if (!h || !h.c || !h.c.length) {
      document.getElementById('chart-stock').innerHTML =
        '<div style="padding:30px;text-align:center;color:#7f8d9f;font-size:12px">该标的无历史序列</div>';
      return;
    }
    var costLine = [];
    for (var q = 0; q < h.c.length; q++) { costLine.push(o.cost); }

    /* 各机制成本线的水平参考线：只画落在价格区间附近的，
       远在区间之外的（如距现价 -30%）画进来会压扁整条股价曲线，交给上方"成本线位置"卡片表达 */
    var cv = h.c.filter(function (x) { return x !== null && x !== undefined && !isNaN(x); });
    var pmin = Math.min.apply(null, cv), pmax = Math.max.apply(null, cv);
    var lo = pmin * 0.94, hi = pmax * 1.06;

    /* 融资追保线与平仓线是这张图的主角，必须尽量落在视野内：
       下限向它们延伸，但最多只到 60 日低点的 70%。再往下拉，股价就被压成一条直线了，
       那种深套标的（平仓线在 60 日低点下方 30% 以上）交给下方"成本线位置"卡片表达。 */
    var callP = o.price * (1 - (o.buf_call || 0) / 100);
    var liqP = o.price * (1 - (o.buf_liq || 0) / 100);
    var finLow = Math.min(nz(callP) ? callP : Infinity, nz(liqP) ? liqP : Infinity);
    /* 留 6% 边距，最低那条线的标签才不会被 x 轴切掉 */
    if (isFinite(finLow)) lo = Math.min(lo, Math.max(finLow * 0.94, pmin * 0.70));

    /* 参考线：先收集、按价格排序，再让相邻两条分置线的上下两侧——
       多条线挤在窄区间时（如质押 7.18 / 追保 6.56 / 平仓 5.68），标签才不会叠成一团 */
    var LINES = [
      { nm: '质押平仓', v: o.pld_line, c: '#ff9f43', ds: false },
      { nm: '转股价', v: o.cb_conv, c: '#4c9aff', ds: false },
      { nm: '追保', v: callP, c: '#f6465d', ds: false },
      { nm: '平仓', v: liqP, c: '#ff6f85', ds: true }
    ].filter(function (x) {
      return x.v !== null && x.v !== undefined && !isNaN(x.v) && Number(x.v) >= lo && Number(x.v) <= hi;
    }).sort(function (a, b) { return Number(a.v) - Number(b.v); });

    /* 标签排布：先按价格换算成像素位置，做一遍最小间距避让，再回推成 distance。
       天马科技这种质押 7.18 / 追保 6.56 / 平仓 5.68 三条线全挤在底部的标的，
       单纯交替上下仍会叠在一起，必须按实际像素坐标推。 */
    var GRID_H = 221;                                  /* 285 - top38 - bottom26 */
    var ys = LINES.map(function (x) { return (hi - Number(x.v)) / (hi - lo) * GRID_H; });
    var adjY = ys.slice();
    var GAP = 19;
    /* 必须按屏幕 y 从上到下推：价格排序是反的（价格越高 y 越小），照价格顺序推会把底部的线继续往下顶 */
    var orderY = ys.map(function (y, i) { return i; }).sort(function (a, b) { return ys[a] - ys[b]; });
    for (var t = 1; t < orderY.length; t++) {
      var pr = orderY[t - 1], cu = orderY[t];
      if (adjY[cu] - adjY[pr] < GAP) adjY[cu] = adjY[pr] + GAP;
    }
    /* 底部要留出标签自身的高度，否则最下面那条线的标签会被绘图区裁掉 */
    var overflow = adjY.length ? adjY[orderY[orderY.length - 1]] - (GRID_H - 24) : 0;
    if (overflow > 0) { for (var u = 0; u < adjY.length; u++) adjY[u] -= overflow; }

    var ml = LINES.map(function (x, i) {
      var v = Number(x.v);
      var dy = adjY[i] - ys[i];
      return {
        yAxis: v, name: x.nm,
        lineStyle: {
          color: x.c, width: x.ds ? 1.3 : 1.2, opacity: 1,
          type: x.ds ? [2.5, 2.5] : 'dashed'
        },
        label: {
          formatter: x.nm + ' ' + v.toFixed(2), color: x.c, fontSize: 10.5,
          position: dy <= 0 ? 'insideStartTop' : 'insideStartBottom',
          distance: Math.abs(dy) + 4,
          backgroundColor: 'rgba(8,12,17,.92)', padding: [2, 5], borderRadius: 2,
          borderColor: x.c, borderWidth: .6, borderType: 'solid'
        }
      };
    });

    /* 追保线与平仓线之间的淡红带：跌破追保只是开始，这里才是被强平的区间 */
    var band = (callP > liqP && liqP < hi && callP > lo)
      ? [[{ yAxis: Math.max(liqP, lo) }, { yAxis: Math.min(callP, hi) }]]
      : null;

    var opt = {
      animation: false,
      grid: { left: 52, right: 54, top: 38, bottom: 26 },
      legend: {
        top: 0, left: 'center', itemWidth: 10, itemHeight: 8, itemGap: 12,
        textStyle: { color: '#7f8d9f', fontSize: 10.5 }
      },
      tooltip: {
        trigger: 'axis', appendToBody: true,
        backgroundColor: '#111821', borderColor: '#22303f',
        textStyle: { color: '#e9eff7', fontSize: 12 },
        formatter: function (ps) {
          var s = ps[0].axisValue + '<br/>';
          ps.forEach(function (p) {
            var u = (p.seriesName === '融资余额') ? ' 亿' : ' 元';
            s += p.marker + p.seriesName + ' <b>' + (p.data === null ? '—' : Number(p.data).toFixed(2)) + u + '</b><br/>';
          });
          return s;
        }
      },
      xAxis: {
        type: 'category', data: HD, boundaryGap: true,
        axisLine: { lineStyle: { color: '#22303f' } },
        axisLabel: { color: '#7f8d9f', fontSize: 10, interval: Math.floor(HD.length / 4) },
        axisTick: { show: false }
      },
      yAxis: [
        {
          type: 'value', name: '融资余额(亿)', nameTextStyle: { color: '#7f8d9f', fontSize: 10 },
          splitLine: { lineStyle: { color: '#1b2634' } },
          axisLabel: { color: '#7f8d9f', fontSize: 10 }
        },
        {
          type: 'value', name: '股价(元)', nameTextStyle: { color: '#7f8d9f', fontSize: 10 },
          min: lo, max: hi,
          splitLine: { show: false },
          axisLabel: {
            color: '#7f8d9f', fontSize: 10,
            showMinLabel: false, showMaxLabel: false,
            formatter: function (v) { return Math.abs(v - Math.round(v)) < 1e-9 ? v : v.toFixed(1); }
          }
        }
      ],
      series: [
        {
          name: '融资余额', type: 'bar', yAxisIndex: 0, data: h.r,
          itemStyle: { color: 'rgba(76,154,255,.5)' }, barWidth: '60%'
        },
        {
          name: '股价', type: 'line', yAxisIndex: 1, data: h.c, symbol: 'none',
          lineStyle: { width: 1.8, color: '#e9eff7' },
          markLine: ml.length ? { silent: true, symbol: 'none', data: ml } : undefined,
          markArea: band ? {
            silent: true,
            itemStyle: { color: 'rgba(246,70,93,.10)' },
            data: band
          } : undefined
        },
        {
          name: '估算成本', type: 'line', yAxisIndex: 1, data: costLine, symbol: 'none',
          lineStyle: { width: 1.2, color: '#f6465d', type: 'dashed' },
          itemStyle: { color: '#f6465d' }
        }
      ]
    };
    CHART('chart-stock', opt);
  }

  function closeDrawer() {
    drawer.classList.remove('on');
    mask.classList.remove('on');
  }

  document.getElementById('tbody').addEventListener('click', function (e) {
    var tr = e.target.closest('tr');
    if (!tr) return;
    var idx = tr.getAttribute('data-i');
    if (idx === null) return;
    openOf(SRC[Number(idx)]);
  });
  document.getElementById('dclose').addEventListener('click', closeDrawer);
  mask.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeDrawer();
  });

  /* ---------------- 初始化 ---------------- */
  applySort();
  render();
  updateHint();
})();
