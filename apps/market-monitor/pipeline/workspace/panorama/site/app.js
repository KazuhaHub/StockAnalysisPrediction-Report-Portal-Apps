/* Panorama 前端：单文件离线。数据来自 data.js（window.PANORAMA），图表走 chart-boot 的 CHART()。 */
(function () {
"use strict";

var P = window.PANORAMA;
if (!P) { document.body.insertAdjacentHTML("afterbegin",
  '<div style="padding:40px;font:15px/1.8 -apple-system">数据未加载（data.js 缺失）。请用 build_report.py 重新构建。</div>'); return; }

var COLS = P.cols, ROWS = P.rows, PCT = P.pct, F = P.factors, META = P.meta;
var S = new Array(ROWS.length);
for (var i = 0; i < ROWS.length; i++) {
  var o = {}; for (var j = 0; j < COLS.length; j++) o[COLS[j]] = ROWS[i][j];
  o._i = i; S[i] = o;
}
var BY = {}; S.forEach(function (s) { BY[s.symbol] = s; });

/* ---------------- 工具 ---------------- */
var C = { ink: "#14202b", sub: "#5d6b78", faint: "#8b96a2", line: "#e2e1da",
  red: "#a8341f", teal: "#1a6b62", gold: "#8f6f1c", blue: "#2a4f7c", grey: "#b9b3a4" };
var PAL = [C.red, C.teal, C.gold, C.blue, "#7a5c9e", "#4a6b3a", "#a86a2f", "#4b7a8c",
  "#8c4b6b", "#6b6b4b"];

function n(v, d) {
  if (v === null || v === undefined || v === "" || (typeof v === "number" && !isFinite(v))) return "—";
  if (typeof v !== "number") return v;
  var s = Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : v.toFixed(d === undefined ? 1 : d);
  return s;
}
function pc(v, d) { return (v === null || v === undefined || !isFinite(v)) ? "—" : (v * 100).toFixed(d === undefined ? 1 : d) + "%"; }
function cls(v, inv) { if (v === null || !isFinite(v)) return ""; return (inv ? v < 0 : v > 0) ? "pos" : (v < 0 ? "neg" : ""); }
function $(id) { return document.getElementById(id); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]; }); }
function count(k) { return META[k] || {}; }

var LBL_ORDER = ["显著低估", "低估", "合理", "高估", "显著高估", "分歧过大", "单一方法参考", "数据不足"];
var LBL_COLOR = { "显著低估": C.teal, "低估": "#4f9b8f", "合理": C.grey, "高估": "#c98b3f", "显著高估": C.red,
  "分歧过大": "#8a7f6b", "单一方法参考": "#a9a293", "数据不足": "#d6d2c6" };

/* ---------------- 表格 ---------------- */
function table(el, spec, rows, opt) {
  opt = opt || {};
  el.innerHTML = "";
  var tb = document.createElement("table");
  var thead = "<thead><tr>" + spec.map(function (c, k) {
    return '<th class="' + (c.l ? "l" : "") + '" data-k="' + k + '">' + c.t + "</th>";
  }).join("") + "</tr></thead>";
  var body = rows.map(function (r) {
    return "<tr>" + spec.map(function (c) {
      var v = c.get ? c.get(r) : r[c.k];
      var txt = c.fmt ? c.fmt(v, r) : (typeof v === "number" ? n(v, c.d) : esc(v));
      var k = c.cls ? c.cls(v, r) : (c.c ? c.c : "");
      return '<td class="' + (c.l ? "l " : "") + k + '">' + txt + "</td>";
    }).join("") + "</tr>";
  }).join("");
  tb.innerHTML = thead + "<tbody>" + body + "</tbody>";
  el.appendChild(tb);
  if (!opt.nosort) {
    var sortK = -1, dir = -1;
    tb.querySelectorAll("th").forEach(function (th) {
      th.addEventListener("click", function () {
        var k = +th.dataset.k;
        dir = (sortK === k) ? -dir : -1;
        sortK = k;
        var c = spec[k];
        var sorted = rows.slice().sort(function (a, b) {
          var va = c.get ? c.get(a) : a[c.k], vb = c.get ? c.get(b) : b[c.k];
          if (va === null || va === undefined) return 1;
          if (vb === null || vb === undefined) return -1;
          return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
        });
        table(el, spec, sorted, opt);
      });
    });
  }
}

/* ---------------- 通用列 ---------------- */
var C_BASE = [
  { k: "symbol", t: "代码", l: 1, c: "sym" },
  { k: "name", t: "名称", l: 1 },
  { k: "sw1", t: "行业", l: 1 },
];
function cScore(k, t) {
  return { k: k, t: t, d: 1, get: function (r) { return r[k]; },
    fmt: function (v) { return v === null ? "—" : '<b class="num">' + n(v, 1) + "</b>"; } };
}

/* ================= 00 落地页 ================= */
function renderHome() {
  var nU = META.n_universe, nP = META.n_price, nPool = META.n_pool, nValid = META.n_valid;
  var nF = META.n_factors, nM = P.methods.length, nInd = META.n_industries, nDiv = META.n_div_cohort;

  $("hero-sub").innerHTML = nF + " 个因子先在申万一级行业内转分位，价值、成长、周期、红利、动量、质量六套策略同时出榜并给共振分；" +
    "再叠一层<b>十法估值</b>——相对行业 PE/PB、自身历史 PE/PB、两阶段 DCF（FCFE / FCFF）、DDM、EPV、PEG、剩余收益，覆盖 <b>" +
    n(nPool, 0) + "</b> 只（有效 <b>" + n(nValid, 0) + "</b>），每只给出综合价、上涨空间、判断标签、参与方法数与分歧度。" +
    "另附<b>反向 DCF</b>：解出当前价格隐含的增速，和历史增速对照。季度随财报更新，动量因子做过分层体检——失效的时候，页面会直接标红。";

  $("strip").innerHTML = [
    [n(nU, 0), "只 A 股（含北交所）", ""],
    [nF, "个财务与量价因子", ""],
    ["6", "套策略 + 共振榜", ""],
    ["12", "个可序列化模板", ""],
    [nM, "种估值方法", ""],
    [n(nPool, 0), "只估值覆盖", "有效 " + n(nValid, 0)]
  ].map(function (x) {
    return '<div class="strip"><div class="k">' + x[1] + '</div><div class="v">' + x[0] +
      (x[2] ? "<small>" + x[2] + "</small>" : "") + "</div></div>";
  }).join("").replace(/<div class="strip">/g, "<div>");

  var mk = P.market;
  $("mk-note").textContent = "PANORAMA / 市场总览 · 2026 年三季报";
  $("mk-kpi").innerHTML = [
    ["全A中位 PE", n(mk.median_pe, 1) + " 倍", "正 PE 股票中位"],
    ["全A中位 PB", n(mk.median_pb, 2) + " 倍", ""],
    ["站上 120 日均线", n(mk.above_ma120_pct, 1) + "%", "等权，本地日线口径"],
    ["站上 250 日均线", n(mk.above_ma250_pct, 1) + "%", ""],
    ["估值覆盖", n(nPool, 0) + " 只", "有效 " + n(nValid, 0)],
    ["股息样本", nDiv + " 只", "股息率 ≥4% 实测"]
  ].map(function (x) {
    return '<div class="card kpi"><div class="k">' + x[0] + '</div><div class="v">' + x[1] +
      '</div><div class="s">' + x[2] + "</div></div>";
  }).join("");

  // 宽度
  var b60 = mk.breadth_60, b250 = mk.breadth_250;
  CHART("c-breadth", {
    grid: { left: 44, right: 12, top: 16, bottom: 26 },
    tooltip: { trigger: "axis", valueFormatter: function (v) { return v + "%"; } },
    xAxis: { type: "category", data: b60.map(function (d) { return d.d.slice(5); }),
      axisLine: { lineStyle: { color: C.line } }, axisLabel: { color: C.faint, fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { color: C.faint, fontSize: 10, formatter: "{value}%" },
      splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: [{ type: "line", data: b60.map(function (d) { return d.v; }), showSymbol: false,
      lineStyle: { width: 2, color: C.red }, areaStyle: { color: "rgba(168,52,31,.08)" } }]
  });
  $("breadth-note").innerHTML = "最新 <b>" + n(b60[b60.length - 1].v, 1) + "%</b>；" +
    "60 日内最高 " + n(Math.max.apply(null, b60.map(function (d) { return d.v; })), 1) + "%、最低 " +
    n(Math.min.apply(null, b60.map(function (d) { return d.v; })), 1) + "%。" +
    "宽度是「温度计」而不是「天气预报」——它描述现在，不预测下一步。";

  // 行业
  var inds = P.industries.filter(function (d) { return avg6(d) !== null; })
    .sort(function (a, b) { return avg6(b) - avg6(a); });
  var mean6 = inds.reduce(function (a, d) { return a + avg6(d); }, 0) / inds.length;
  var pick = inds.slice(0, 7).concat(inds.slice(-7));
  var amax = 0;
  pick.forEach(function (d) { var v = Math.abs(avg6(d) - mean6); if (v > amax) amax = v; });
  amax = Math.max(1, amax * 1.25);
  CHART("c-ind", {
    grid: { left: 92, right: 52, top: 18, bottom: 22 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" },
      formatter: function (ps) { var p = axisPick(ps); return p.name + "：偏离 " + (p.value > 0 ? "+" : "") + p.value.toFixed(1) + " 分（六策略均分 " + (mean6 + p.value).toFixed(1) + "）"; } },
    xAxis: { type: "value", min: -amax, max: amax, axisLabel: { color: C.faint, fontSize: 10, formatter: function (v) { return (v > 0 ? "+" : "") + v.toFixed(1); } },
      splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", inverse: true, data: pick.map(function (d) { return d.name; }),
      axisLabel: { color: C.sub, fontSize: 11 }, axisLine: { lineStyle: { color: C.line } } },
    series: (function () {
      var sv = divBars(pick.map(function (d) { return avg6(d) - mean6; }), 10.5, 0);
      sv[0].markLine = { silent: true, symbol: "none", lineStyle: { color: C.ink, width: 1 },
        data: [{ xAxis: 0 }], label: { show: false } };
      return sv;
    })()
  });

  // 标签 donut
  var lb = count("labels");
  var LBL_SHORT = { "单一方法参考": "单法参考", "分歧过大": "分歧大", "数据不足": "数据不足" };
  CHART("c-label", {
    tooltip: { trigger: "item", formatter: "{b}: {c} 只 ({d}%)" },
    series: [{ type: "pie", radius: ["46%", "68%"], center: ["50%", "52%"],
      itemStyle: { borderColor: "#fff", borderWidth: 2 },
      label: { fontSize: 9.5, color: C.sub, formatter: function (p) {
        return (LBL_SHORT[p.name] || p.name) + "\n" + p.value; } },
      labelLine: { length: 6, length2: 8, lineStyle: { color: "#cfcabf" } },
      labelLayout: { hideOverlap: true },
      data: LBL_ORDER.filter(function (k) { return lb[k]; }).map(function (k) {
        return { name: k, value: lb[k], itemStyle: { color: LBL_COLOR[k] } };
      }) }]
  });

  var qd = count("quads");
  CHART("c-quad", {
    tooltip: { trigger: "item", formatter: "{b}: {c} 只" },
    series: [{ type: "pie", radius: ["46%", "74%"], center: ["50%", "52%"],
      itemStyle: { borderColor: "#fff", borderWidth: 2 },
      label: { fontSize: 10, color: C.sub, formatter: "{b}\n{c}" },
      labelLayout: { hideOverlap: true },
      data: ["便宜好公司", "价值陷阱", "优质但贵", "又贵又差"].filter(function (k) { return qd[k]; })
        .map(function (k, i) { return { name: k, value: qd[k], itemStyle: { color: [C.teal, C.gold, C.blue, C.red][i] } }; }) }]
  });

  // 本期最重要的一件事
  var band = P.health.factors["MOM_12_1"] || {};
  $("alert-box").innerHTML =
    '<div style="font-family:var(--f-display);font-size:19px;color:var(--ink);line-height:1.4">动量在这里是反向的</div>' +
    '<p style="margin:8px 0 0">' + P.health.n_dates + " 个月度调仓点上，12-1 动量的 20 日 Rank IC 均值 <b class=\"num\" style=\"color:var(--red)\">" +
    n(band.ic20_mean, 3) + "</b>，胜率 <b>" + n(band.ic20_win * 100, 0) + "%</b>；五分层里 Q5 反而最差（Q5−Q1 = " +
    n(P.health.momentum_summary.Q5_Q1, 2) + "pp，单调性 " + (P.health.momentum_summary.mono ? "成立" : "不成立") + "）。" +
    "<br><br>所以动量策略的榜单<b>请反向读</b>：它不是「买最强的」，而是「本期最强的那批在跑输」。这不是 bug，是 regime。</p>";

  // 方法卡
  $("methods").innerHTML = P.methods.map(function (m) {
    return '<div class="mcard"><div class="code">' + m.id + '</div><h4>' + m.name + "</h4>" +
      '<div class="cov">覆盖 <b>' + n(m.cov, 0) + "</b> 只 · 权重 " + n(m.weight, 1) + "</div></div>";
  }).join("");

  CHART("c-methodcov", {
    grid: { left: 96, right: 44, top: 10, bottom: 22 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", data: P.methods.map(function (m) { return m.id; }).reverse(),
      axisLabel: { color: C.sub, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
    series: [{ type: "bar", data: P.methods.map(function (m) { return m.cov; }).reverse(),
      barWidth: "60%", itemStyle: { color: C.blue, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: "right", fontSize: 10, color: C.sub } }]
  });
  var mc = P.methods.map(function (m) { return m.cov; });
  $("methodcov-note").innerHTML = "覆盖最窄的是 <b>DDM " + n(P.methods[6].cov, 0) + " 只</b>（只有可观测到股息率的样本），" +
    "最宽的是 <b>PB 相对行业 " + n(P.methods[1].cov, 0) + " 只</b>。方法覆盖率直接列在每只股票上，不用平均数掩盖缺口。";

  $("care").innerHTML =
    "<p style='margin:0 0 8px'><b>分歧大就不给结论。</b>同时满足「≥2 个方法可用」且「分歧不在行业内前 " +
    (100 - META.disp_pct_gate) + "%」才输出综合价；仅一种方法可用的标「单一方法参考」，无方法的标「数据不足」，两者都不输出综合价。</p>" +
    "<p style='margin:0 0 8px'><b>假设全部公开。</b>无风险利率 <span class='num'>" + (META.rf * 100).toFixed(2) + "%</span>、股权风险溢价 <span class='num'>" +
    (META.erp * 100).toFixed(1) + "%</span>、永续增长 <span class='num'>" + (META.g_term * 100).toFixed(1) + "%</span>、预测期 <span class='num'>" +
    META.years + " 年</span>、Ke 下限 8.5%，全部写在「方法与数据」页。</p>" +
    "<p style='margin:0'><b>绝对法偏保守。</b>DCF / EPV / RI 在 8.5% 股权成本下系统性地低于市价，所以综合价的标签分布是「高估多、低估少」——" +
    "这是结论不是 bug。跨股票比较请优先看同行业内的相对位置。</p>";

  // 策略列表
  var keys = ["value", "growth", "cyclical", "dividend", "momentum", "quality"];
  $("strat-list").innerHTML = keys.map(function (k) {
    var s = P.strategies[k], w = s.w, nf = Object.keys(w).length;
    var fnames = Object.keys(w).sort(function (a, b) { return w[b] - w[a]; }).slice(0, 2).join(" / ");
    var tpl = s.templates.map(function (t) { return t.id + " " + t.name; }).join(" · ");
    return '<div class="srow"><div><h4>' + s.name + '策略</h4><div class="en">' + s.en.toUpperCase() + "</div></div>" +
      "<div><p>" + s.desc + '</p><p style="color:var(--faint);font-size:12px;margin-top:4px">模板：' + tpl + "</p></div>" +
      '<div class="f">' + nf + " 个因子 · 权重合计 100<br>" + fnames + "</div></div>";
  }).join("");
  $("strat-note").textContent = "12 个模板，点开即对全市场求交";

  // 页面导览
  var pages = [
    ["01", "市场总览", "宽度曲线、六策略行业热力、共振榜"],
    ["02", "策略中心", "因子权重、2 个模板、可筛选榜单"],
    ["03", "选股器", "54 因子勾选 + 权重滑杆、实时重算"],
    ["04", "个股估值", "十法结论全表、四象限、单票拆解"],
    ["05", "策略对比", "6×6 交集矩阵、风格象限、相关性"],
    ["06", "因子库", "方向、覆盖率、实测 IC"],
    ["07", "方法与数据", "口径、假设、陷阱、体检"],
    ["08", "反向 DCF", "每只股票的市价隐含增速"]
  ];
  $("pageroad").innerHTML = pages.map(function (p) {
    return "<div><div class='no'>" + p[0] + "</div><b>" + p[1] + "</b><span>" + p[2] + "</span></div>";
  }).join("");

  var bp = P.health.factors.BP, lv = P.health.factors.LOW_VOL, roe = P.health.factors.ROE;
  $("health-note").innerHTML = "动量是最容易失效的一类因子。" + P.health.n_dates + " 个月度截面上：BP 的 IC <b>" +
    n(bp.ic20_mean, 3) + "</b>（胜率 " + n(bp.ic20_win * 100, 0) + "%）、低波动 <b>" + n(lv.ic20_mean, 3) + "</b>（胜率 " +
    n(lv.ic20_win * 100, 0) + "%）、ROE <b>" + n(roe.ic20_mean, 3) + "</b>、动量 <b style='color:var(--red)'>" +
    n(band.ic20_mean, 3) + "</b>。这一期真正有效的只有<b>低估值和低波动</b>。";

  $("warn-landing").innerHTML = "<b>读之前先知道三件事：</b>① 股息率只有 " + nDiv +
    " 只样本（≥4% 的高息股），红利策略与 DDM 的结论只在这批股票上成立；② 量价因子覆盖 " + n(META.n_price, 0) +
    " 只价格，因子体检用的本地日线库已补到 " + n(P.health.n_codes, 0) + " 只（全市场 " + n(P.market.n_stocks, 0) +
    " 只，北交所因无日线数据源整块缺席），上市不满一年的票动量分为空；③ 财务为 2026 三季报 PIT 口径，" +
    "价格截至 2026-11-13，不做盘中更新。";

  $("can-do").innerHTML = "<p style='margin:0'>• 在<b>同一把尺子</b>下比较不同行业的便宜程度（行业内分位）</p>" +
    "<p style='margin:6px 0 0'>• 看一只股票被几种方法认可、分歧有多大</p>" +
    "<p style='margin:6px 0 0'>• 用十个因子自组策略，客户端实时重算，导出 CSV</p>" +
    "<p style='margin:6px 0 0'>• 用反向 DCF 追问「现在的价格在假设什么增速」</p>";
  $("cant-do").innerHTML = "<p style='margin:0'>• 不预测未来盈利，所有估值都用已披露财务</p>" +
    "<p style='margin:6px 0 0'>• 不处理流动性、停牌、交易成本、涨跌停</p>" +
    "<p style='margin:6px 0 0'>• 不做行业内打分之外的行业配置建议</p>" +
    "<p style='margin:6px 0 0'>• 不构成买卖指令——输出的候选池需要你自己做第二层判断</p>";
}

function avg6(d) {
  var ks = ["s_value", "s_growth", "s_cyclical", "s_dividend", "s_momentum", "s_quality"];
  var t = 0, c = 0;
  for (var i = 0; i < ks.length; i++) {
    var v = d[ks[i]];
    if (v !== null && v !== undefined && isFinite(v)) { t += v; c++; }
  }
  return c ? t / c : null;
}

/* ================= 01 总览 ================= */
function renderOverview() {
  var mk = P.market, lb = count("labels"), qd = count("quads");
  $("ov-meta").textContent = "AS OF " + mk.asof + " · " + n(META.n_pool, 0) + " 只入池";
  $("ov-kpi").innerHTML = [
    ["中位 PE", n(mk.median_pe, 1)], ["中位 PB", n(mk.median_pb, 2)],
    ["站上 120MA", n(mk.above_ma120_pct, 1) + "%"], ["站上 250MA", n(mk.above_ma250_pct, 1) + "%"],
    ["低估+显著低估", n((lb["低估"] || 0) + (lb["显著低估"] || 0), 0)],
    ["高估+显著高估", n((lb["高估"] || 0) + (lb["显著高估"] || 0), 0)]
  ].map(function (x) {
    return '<div class="card kpi"><div class="k">' + x[0] + '</div><div class="v">' + x[1] + "</div></div>";
  }).join("");

  CHART("c-ov-breadth", lineOpt(mk.breadth_60, C.red));
  var ew = mk.ew_index.slice(), ew0 = ew.length ? ew[0].v : 1;
  CHART("c-ov-index", lineOpt(ew.map(function (d) { return { d: d.d, v: d.v / ew0 }; }), C.blue, 2));

  var indAll = P.industries.filter(function (d) { return avg6(d) !== null; })
    .sort(function (a, b) { return avg6(b) - avg6(a); });
  var mn6 = indAll.reduce(function (a, d) { return a + avg6(d); }, 0) / indAll.length;
  var inds = indAll.length > 18 ? indAll.slice(0, 9).concat(indAll.slice(-9)) : indAll;
  var bmax = 0;
  inds.forEach(function (d) { var v = Math.abs(avg6(d) - mn6); if (v > bmax) bmax = v; });
  bmax = Math.max(1, bmax * 1.12);
  CHART("c-ov-ind", {
    grid: { left: 86, right: 34, top: 10, bottom: 30 },
    tooltip: { trigger: "axis", formatter: function (ps) {
      var p = axisPick(ps); return p.name + "：偏离 " + (p.value > 0 ? "+" : "") + p.value.toFixed(1) + " 分（均分 " + (mn6 + p.value).toFixed(1) + "）"; } },
    xAxis: { type: "value", min: -bmax, max: bmax, axisLabel: { color: C.faint, fontSize: 10, formatter: function (v) { return (v > 0 ? "+" : "") + v.toFixed(1); } }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", inverse: true, data: inds.map(function (d) { return d.name; }), axisLabel: { color: C.sub, fontSize: 10.5 }, axisLine: { lineStyle: { color: C.line } } },
    dataZoom: [{ type: "inside", yAxisIndex: 0 }],
    series: (function () {
      var sv = divBars(inds.map(function (d) { return avg6(d) - mn6; }), 10, 0);
      sv[0].markLine = { silent: true, symbol: "none", lineStyle: { color: C.ink, width: 1 },
        data: [{ xAxis: 0 }], label: { show: false } };
      return sv;
    })()
  });

  CHART("c-ov-label", {
    tooltip: { trigger: "item" },
    legend: { bottom: 0, textStyle: { fontSize: 10, color: C.sub }, itemWidth: 9, itemHeight: 9 },
    series: [{ type: "bar", data: LBL_ORDER.map(function (k) { return lb[k] || 0; }), barWidth: "50%",
      itemStyle: { color: function (p) { return LBL_COLOR[LBL_ORDER[p.dataIndex]]; }, borderRadius: [3, 3, 0, 0] },
      label: { show: true, position: "top", fontSize: 10, color: C.sub } }],
    xAxis: { type: "category", data: LBL_ORDER, axisLabel: { color: C.faint, fontSize: 9, interval: 0, rotate: 30 }, axisLine: { lineStyle: { color: C.line } } },
    yAxis: { type: "value", axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    grid: { left: 46, right: 12, top: 22, bottom: 54 }
  });

  var top = S.filter(function (s) { return s.resonance !== null && s.price !== null; })
    .sort(function (a, b) { return b.resonance - a.resonance; }).slice(0, 30);
  table($("t-resonance"), C_BASE.concat([
    { k: "price", t: "价格", d: 2 }, { k: "mktcap_yi", t: "市值(亿)", d: 0 },
    { k: "pe", t: "PE", d: 1 }, { k: "pb", t: "PB", d: 2 },
    cScore("s_value", "价值"), cScore("s_growth", "成长"), cScore("s_cyclical", "周期"),
    cScore("s_dividend", "红利"), cScore("s_momentum", "动量"), cScore("s_quality", "质量"),
    { k: "resonance", t: "共振分", d: 1, fmt: function (v) { return '<b class="num" style="color:' + C.red + '">' + n(v, 1) + "</b>"; } },
    { k: "label", t: "估值标签", l: 1, fmt: function (v) { return v ? '<span class="tag">' + v + "</span>" : "—"; } }
  ]), top);
}

/* 双向柱：正负分两个系列，标签才能稳定落在柱子外侧（position 回调在部分版本不生效） */
function divBars(vals, fs, gate) {
  var lab = { show: true, fontSize: fs, color: C.sub, distance: 5,
    formatter: function (p) {
      if (p.value === null || p.value === undefined) return "";
      return Math.abs(p.value) >= gate ? (p.value > 0 ? "+" : "") + p.value.toFixed(1) : "";
    } };
  return [
    { type: "bar", name: "高于中位", barGap: "-100%", barWidth: "58%",
      data: vals.map(function (v) { return v >= 0 ? v : null; }),
      itemStyle: { color: C.teal, borderRadius: [0, 3, 3, 0] },
      label: { show: true, fontSize: fs, color: C.sub, distance: 5,
        position: "right", formatter: lab.formatter } },
    { type: "bar", name: "低于中位", barGap: "-100%", barWidth: "58%",
      data: vals.map(function (v) { return v < 0 ? v : null; }),
      itemStyle: { color: C.red, borderRadius: [3, 0, 0, 3] },
      label: { show: true, fontSize: fs, color: C.sub, distance: 5,
        position: "left", formatter: lab.formatter } }
  ];
}
function axisPick(ps) {
  for (var i = 0; i < ps.length; i++) if (ps[i].value !== null && ps[i].value !== undefined) return ps[i];
  return ps[0];
}

function lineOpt(arr, color, bits) {
  return {
    grid: { left: 46, right: 14, top: 16, bottom: 26 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: arr.map(function (d) { return d.d.slice(5); }),
      axisLabel: { color: C.faint, fontSize: 10, interval: Math.ceil(arr.length / 8) },
      axisLine: { lineStyle: { color: C.line } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: C.faint, fontSize: 10 },
      splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: [{ type: "line", data: arr.map(function (d) { return d.v; }), showSymbol: false,
      lineStyle: { width: 1.8, color: color },
      areaStyle: bits === 2 ? null : { color: "rgba(168,52,31,.08)" } }]
  };
}

/* ================= 02 策略中心 ================= */
var stKey = "value";
function renderStrategy() {
  var keys = ["value", "growth", "cyclical", "dividend", "momentum", "quality"];
  $("seg-strat").innerHTML = keys.map(function (k) {
    return '<button data-k="' + k + '" class="' + (k === stKey ? "on" : "") + '">' + P.strategies[k].name + "</button>";
  }).join("");
  $("seg-strat").querySelectorAll("button").forEach(function (b) {
    b.addEventListener("click", function () { stKey = b.dataset.k; renderStrategy(); });
  });

  var s = P.strategies[stKey], w = s.w;
  $("st-desc").textContent = s.desc;
  $("st-meta").textContent = Object.keys(w).length + " 个因子 · 权重合计 " + Object.keys(w).reduce(function (a, k) { return a + w[k]; }, 0) +
    " · 平均覆盖率 " + n((META.coverage[stKey] || {}).mean * 100, 0) + "%";
  if (stKey === "momentum") $("st-meta").textContent += " · ⚠ 本期 IC 为负，榜单宜反向读";

  var items = Object.keys(w).sort(function (a, b) { return w[b] - w[a]; }).map(function (fid) {
    var f = F.filter(function (x) { return x.id === fid; })[0] || { name: fid };
    return { name: f.name, w: w[fid] };
  });
  CHART("c-st-w", {
    grid: { left: 120, right: 40, top: 10, bottom: 22 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", max: 25, axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", data: items.map(function (x) { return x.name; }).reverse(),
      axisLabel: { color: C.sub, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
    series: [{ type: "bar", data: items.map(function (x) { return x.w; }).reverse(), barWidth: "62%",
      itemStyle: { color: stKey === "momentum" ? C.red : C.teal, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: "right", fontSize: 10, color: C.sub } }]
  });

  var sk = "s_" + stKey;
  $("st-tpl").innerHTML = s.templates.map(function (t) {
    return '<div class="fitem" style="margin-bottom:8px"><div class="t"><label><b>' + t.id + " " + t.name +
      '</b></label><span class="w">' + n(t.n, 0) + ' 只</span></div><div class="meta2">' + t.desc + "</div></div>";
  }).join("");

  var vals = S.map(function (x) { return x[sk]; }).filter(function (v) { return v !== null; });
  var bins = 10, mn = 0, mx = 100, step = (mx - mn) / bins, hist = new Array(bins).fill(0);
  vals.forEach(function (v) { var k = Math.min(bins - 1, Math.max(0, Math.floor((v - mn) / step))); hist[k]++; });
  CHART("c-st-dist", {
    grid: { left: 44, right: 12, top: 12, bottom: 24 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: hist.map(function (_, i) { return (mn + i * step).toFixed(0); }),
      axisLabel: { color: C.faint, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
    yAxis: { type: "value", axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: [{ type: "bar", data: hist, barWidth: "82%", itemStyle: { color: "#c9c3b4" } }]
  });

  // 行业下拉
  var sel = $("st-ind");
  if (sel.options.length <= 1) {
    P.industries.forEach(function (d) { sel.insertAdjacentHTML("beforeend", "<option>" + d.name + "</option>"); });
    sel.addEventListener("change", paintStratTable);
    $("st-min").addEventListener("change", paintStratTable);
  }
  paintStratTable();
}
function paintStratTable() {
  var sk = "s_" + stKey, ind = $("st-ind").value, mn = +$("st-min").value;
  var rows = S.filter(function (x) {
    return x[sk] !== null && (!ind || x.sw1 === ind) && x[sk] >= mn && x.price !== null;
  }).sort(function (a, b) { return b[sk] - a[sk]; }).slice(0, 300);
  table($("t-strategy"), C_BASE.concat([
    { k: "price", t: "价格", d: 2 }, { k: "mktcap_yi", t: "市值(亿)", d: 0 },
    { k: sk, t: P.strategies[stKey].name + "分", d: 1, fmt: function (v) { return v === null ? "—" : "<b class='num'>" + n(v, 1) + "</b>"; } },
    { k: "pe", t: "PE", d: 1 }, { k: "pb", t: "PB", d: 2 },
    { k: "roe", t: "ROE", d: 1 }, { k: "rev_yoy", t: "营收同比", d: 1 },
    { k: "np_yoy", t: "净利同比", d: 1 },
    { k: "upside", t: "上涨空间", get: function (r) { return r.upside; },
      fmt: function (v) { return v === null ? "—" : '<span class="' + cls(v) + '">' + pc(v, 0) + "</span>"; } },
    { k: "label", t: "标签", l: 1, fmt: function (v) { return v ? '<span class="tag">' + v + "</span>" : "—"; } }
  ]), rows);
}

/* ================= 03 选股器 ================= */
var scW = {};
function renderScreener() {
  var nf = document.getElementById("sc-nf"); if (nf) nf.textContent = F.length;
  var groups = ["价值", "成长", "质量", "周期", "动量", "风险"];
  var html = groups.map(function (g) {
    return '<div style="grid-column:1/-1;margin:12px 0 2px" class="eyebrow">' + g + "</div>" +
      F.filter(function (f) { return f.group === g; }).map(function (f) {
        var w = scW[f.id] === undefined ? "" : scW[f.id];
        return '<div class="fitem" data-f="' + f.id + '">' +
          '<div class="t"><label><input type="checkbox" ' + (scW[f.id] > 0 ? "checked" : "") + ' data-f="' + f.id + '"> ' +
          esc(f.name) + '</label><span class="w" data-w="' + f.id + '">' + (scW[f.id] || "") + "</span></div>" +
          '<input type="range" min="0" max="20" value="' + (scW[f.id] || 0) + '" data-f="' + f.id + '">' +
          '<div class="meta2">覆盖 ' + n(f.coverage * 100, 0) + "% · " + (f.dir > 0 ? "越大越好" : "越小越好") + "</div></div>";
      }).join("");
  }).join("");
  $("sc-factors").innerHTML = html;
  $("sc-factors").querySelectorAll("input[type=range]").forEach(function (r) {
    r.addEventListener("input", function () {
      var id = r.dataset.f, v = +r.value;
      scW[id] = v;
      r.closest(".fitem").querySelector("[data-w]").textContent = v || "";
      r.closest(".fitem").classList.toggle("on", v > 0);
      var cb = r.closest(".fitem").querySelector("input[type=checkbox]");
      if (cb) cb.checked = v > 0;
    });
  });
  $("sc-factors").querySelectorAll("input[type=checkbox]").forEach(function (c) {
    c.addEventListener("change", function () {
      var id = c.dataset.f;
      if (!c.checked) { scW[id] = 0; var r = c.closest(".fitem").querySelector("input[type=range]"); r.value = 0; c.closest(".fitem").querySelector("[data-w]").textContent = ""; c.closest(".fitem").classList.remove("on"); }
      else if (!scW[id]) { scW[id] = 5; var r2 = c.closest(".fitem").querySelector("input[type=range]"); r2.value = 5; c.closest(".fitem").querySelector("[data-w]").textContent = 5; c.closest(".fitem").classList.add("on"); }
    });
  });
  var sel = $("sc-ind");
  if (sel.options.length <= 1) P.industries.forEach(function (d) { sel.insertAdjacentHTML("beforeend", "<option>" + d.name + "</option>"); });
  $("sc-run").onclick = runScreener;
  $("sc-reset").onclick = function () { scW = {}; renderScreener(); };
  $("sc-save").onclick = function () {
    localStorage.setItem("panorama_scheme", JSON.stringify(scW));
    $("sc-hint").textContent = "已存到本地（localStorage），下次点「读方案」恢复";
  };
  $("sc-load").onclick = function () {
    try { scW = JSON.parse(localStorage.getItem("panorama_scheme") || "{}"); renderScreener(); $("sc-hint").textContent = "已读回方案"; }
    catch (e) { $("sc-hint").textContent = "没有找到已存方案"; }
  };
  $("sc-csv").onclick = function () { exportCSV(); };
  if (!Object.keys(scW).length) { // 默认给一套「低估值 + 高质量」
    scW = { BP: 18, EP: 14, PE_HCHEAP: 10, ROE: 14, OCF_NI: 10, LOW_LEV: 8, LOW_VOL: 10, MOM_12_1: 0 };
    renderScreener();
  }
  runScreener();
}

var lastScr = [];
function runScreener() {
  var ids = Object.keys(scW).filter(function (k) { return scW[k] > 0; });
  if (!ids.length) { $("sc-count").textContent = "至少勾选一个因子"; return; }
  var totW = ids.reduce(function (a, k) { return a + scW[k]; }, 0);
  var ind = $("sc-ind").value, cap = +$("sc-cap").value;
  var out = [];
  for (var i = 0; i < S.length; i++) {
    var s = S[i];
    if (s.price === null) continue;
    if (ind && s.sw1 !== ind) continue;
    if (cap === 1 && !(s.mktcap_yi >= 50)) continue;
    if (cap === 2 && !(s.mktcap_yi >= 100)) continue;
    if (cap === 3 && !(s.mktcap_yi >= 50 && s.mktcap_yi <= 300)) continue;
    if (cap === 4 && !(s.mktcap_yi <= 100)) continue;
    var num = 0, den = 0;
    for (var k = 0; k < ids.length; k++) {
      var arr = PCT[ids[k]];
      var v = arr ? arr[i] : null;
      if (v === null || v === undefined) continue;
      num += v * scW[ids[k]]; den += scW[ids[k]];
    }
    if (!den) continue;
    var cov = den / totW;
    var raw = num / den;
    var score = raw - 8 * (1 - cov) - 0.06 * Math.max(0, (volPct(s) - 75));
    out.push({ s: s, score: score, cov: cov });
  }
  out.sort(function (a, b) { return b.score - a.score; });
  lastScr = out;
  $("sc-count").innerHTML = "命中 <b>" + n(out.length, 0) + "</b> 只（因子 " + ids.length + " 个，权重合计 " + totW + "）";
  var rows = out.slice(0, 300).map(function (x) {
    var o = Object.assign({}, x.s); o._score = x.score; o._cov = x.cov; return o;
  });
  table($("t-screener"), C_BASE.concat([
    { k: "price", t: "价格", d: 2 }, { k: "mktcap_yi", t: "市值(亿)", d: 0 },
    { k: "_score", t: "自定义分", d: 1, fmt: function (v) { return v === null ? "—" : "<b class='num' style='color:" + C.red + "'>" + n(v, 1) + "</b>"; } },
    { k: "_cov", t: "覆盖率", d: 0, fmt: function (v) { return n(v * 100, 0) + "%"; } },
    { k: "pe", t: "PE", d: 1 }, { k: "pb", t: "PB", d: 2 }, { k: "roe", t: "ROE", d: 1 },
    { k: "np_yoy", t: "净利同比", d: 1 },
    { k: "upside", t: "上涨空间", fmt: function (v) { return v === null ? "—" : '<span class="' + cls(v) + '">' + pc(v, 0) + "</span>"; } },
    { k: "label", t: "标签", l: 1, fmt: function (v) { return v ? '<span class="tag">' + v + "</span>" : "—"; } }
  ]), rows);
}
var _volP = null;
function volPct(s) {
  if (!_volP) {
    var arr = S.map(function (x) { return x.vol_ann; }).filter(function (v) { return v !== null; }).sort(function (a, b) { return a - b; });
    _volP = arr;
  }
  if (s.vol_ann === null) return 50;
  var lo = 0, hi = _volP.length - 1;
  while (lo < hi) { var mid = (lo + hi) >> 1; if (_volP[mid] < s.vol_ann) lo = mid + 1; else hi = mid; }
  return lo / _volP.length * 100;
}
function exportCSV() {
  if (!lastScr.length) return;
  var head = ["代码", "名称", "行业", "价格", "市值亿", "自定义分", "覆盖率", "PE", "PB", "ROE", "上涨空间", "标签"];
  var lines = [head.join(",")];
  lastScr.slice(0, 1000).forEach(function (x) {
    var s = x.s;
    lines.push([s.symbol, s.name, s.sw1, s.price, s.mktcap_yi, x.score.toFixed(1),
      (x.cov * 100).toFixed(0) + "%", s.pe, s.pb, s.roe,
      s.upside === null ? "" : (s.upside * 100).toFixed(1) + "%", s.label].join(","));
  });
  var blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "panorama_screen_" + new Date().toISOString().slice(0, 10) + ".csv";
  a.click();
}

/* ================= 04 个股估值 ================= */
function renderValuation() {
  var lb = count("labels");
  $("va-meta").textContent = "估值日 " + META.asof + " · 入池 " + n(META.n_pool, 0) + " 只";
  $("va-kpi").innerHTML = [
    ["入池", n(META.n_pool, 0), "有价且有方法"], ["有效（给结论）", n(META.n_valid, 0), "≥2 方法且无大分歧"],
    ["低估+显著低估", n((lb["低估"] || 0) + (lb["显著低估"] || 0), 0), ""],
    ["不出结论", n((lb["分歧过大"] || 0) + (lb["单一方法参考"] || 0) + (lb["数据不足"] || 0), 0), "分歧/单方法/缺数据"]
  ].map(function (x) {
    return '<div class="card kpi"><div class="k">' + x[0] + '</div><div class="v">' + x[1] +
      '</div><div class="s">' + x[2] + "</div></div>";
  }).join("");

  var sel = $("va-ind");
  if (sel.options.length <= 1) {
    P.industries.forEach(function (d) { sel.insertAdjacentHTML("beforeend", "<option>" + d.name + "</option>"); });
    sel.addEventListener("change", paintValTable);
    $("va-label").addEventListener("change", paintValTable);
  }
  $("va-go").onclick = function () { detail($("va-q").value.trim()); };
  $("va-q").addEventListener("keydown", function (e) { if (e.key === "Enter") detail(this.value.trim()); });

  // 各方法给出的估值水平：估值/现价中位（1.0× = 与现价持平），柱子右侧标覆盖只数
  var mRev = P.methods.slice().reverse();
  CHART("c-va-cov", {
    grid: { left: 74, right: 74, top: 14, bottom: 26 },
    tooltip: { trigger: "axis", formatter: function (ps) {
      var p = ps[0], m = mRev[p.dataIndex];
      return p.name + "<br>估值/现价中位 <b>" + (p.value === null ? "—" : p.value.toFixed(2) + "×") +
        "</b><br>覆盖 " + n(m.cov, 0) + " 只";
    } },
    xAxis: { type: "value", min: 0, max: 1.7, axisLabel: { color: C.faint, fontSize: 10, formatter: "{value}×" },
      splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", data: mRev.map(function (m) { return m.id; }),
      axisLabel: { color: C.sub, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
    series: [{ type: "bar", barWidth: "54%",
      data: mRev.map(function (m) {
        var v = m.med_ratio;
        return { value: v, itemStyle: { color: v >= 1.15 ? C.red : (v >= 0.85 ? C.gold : C.teal),
          borderRadius: [0, 3, 3, 0] },
          label: { show: true, position: "right", fontSize: 9.5, color: C.sub,
            formatter: (v === null ? "" : v.toFixed(2) + "×") + "   " + n(m.cov, 0) } };
      }),
      markLine: { silent: true, symbol: "none", lineStyle: { color: C.ink, width: 1, type: "dashed" },
        data: [{ xAxis: 1 }], label: { formatter: "现价 1.0×", fontSize: 9.5, color: C.ink, position: "start" } } }]
  });
  var pf = count("profiles");
  CHART("c-va-profile", {
    tooltip: { trigger: "item" },
    series: [{ type: "pie", radius: ["48%", "76%"], center: ["50%", "52%"],
      itemStyle: { borderColor: "#fff", borderWidth: 2 },
      label: { fontSize: 11, color: C.sub, formatter: "{b}\n{c}" },
      labelLayout: { hideOverlap: true },
      data: Object.keys(pf).map(function (k, i) { return { name: k, value: pf[k], itemStyle: { color: PAL[i] } }; }) }]
  });

  // 四象限散点（抽样 2500）
  var pts = S.filter(function (s) { return s.upside !== null && s.s_quality !== null; });
  var step2 = Math.max(1, Math.floor(pts.length / 2500));
  var sp = pts.filter(function (_, i) { return i % step2 === 0; }).map(function (s) {
    return [Math.max(-1.2, Math.min(1.5, s.upside)), s.s_quality, s.name, s.symbol, s.label || ""];
  });
  CHART("c-va-quad", {
    grid: { left: 48, right: 18, top: 16, bottom: 34 },
    tooltip: { formatter: function (p) { return p.data[2] + " (" + p.data[3] + ")<br>上涨空间 " + (p.data[0] * 100).toFixed(0) + "%<br>质量分 " + p.data[1].toFixed(1) + "<br>" + p.data[4]; } },
    xAxis: { type: "value", name: "上涨空间", nameTextStyle: { color: C.faint, fontSize: 10 },
      axisLabel: { color: C.faint, fontSize: 10, formatter: function (v) { return (v * 100).toFixed(0) + "%"; } },
      splitLine: { lineStyle: { color: "#f0eee7" } }, min: -1, max: 1.5 },
    yAxis: { type: "value", name: "质量分", nameTextStyle: { color: C.faint, fontSize: 10 },
      axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: [{ type: "scatter", data: sp, progressive: 0, large: false, symbolSize: 4,
      itemStyle: { color: "rgba(42,79,124,.45)" },
      markLine: { silent: true, symbol: "none", lineStyle: { color: C.gold, type: "dashed" },
        data: [{ xAxis: 0.25 }, { yAxis: 50 }], label: { show: false } } }]
  });
  $("va-quad-legend").innerHTML =
    '<span><i style="background:' + C.teal + '"></i>右下=便宜好公司（上涨空间>25% 且质量前 50%）</span>' +
    '<span><i style="background:' + C.gold + '"></i>左下=价值陷阱</span>' +
    '<span><i style="background:' + C.blue + '"></i>右上=优质但贵</span>' +
    '<span><i style="background:' + C.red + '"></i>左上=又贵又差</span>';

  paintValTable();
  var first = S.filter(function (s) { return s.symbol === "600519"; })[0] || S.filter(function (s) { return s.composite !== null; })[0];
  if (first) detail(first.symbol);
}
function paintValTable() {
  var ind = $("va-ind").value, lab = $("va-label").value;
  var rows = S.filter(function (s) {
    return s.price !== null && s.composite !== null && (!ind || s.sw1 === ind) && (!lab || s.label === lab);
  }).sort(function (a, b) {
    // 方法数不足 4 的排后面：单一方法给出的极端上涨空间不该占据榜首
    var ga = a.n_methods >= 4 ? 0 : 1, gb = b.n_methods >= 4 ? 0 : 1;
    if (ga !== gb) return ga - gb;
    return (b.upside || -9) - (a.upside || -9);
  }).slice(0, 400);
  var spec = C_BASE.concat([
    { k: "price", t: "价格", d: 2 }, { k: "mktcap_yi", t: "市值(亿)", d: 0 },
    { k: "pe", t: "PE", d: 1 }, { k: "pb", t: "PB", d: 2 },
    { k: "roae", t: "ROE", get: function (r) { return r.roe; }, d: 1 },
    { k: "n_methods", t: "方法数", d: 0 },
    { k: "composite", t: "综合价", d: 2 },
    { k: "upside", t: "上涨空间", fmt: function (v, r) {
        if (v === null) return "—";
        var gated = r.label === "分歧过大" || r.label === "单一方法参考" || r.label === "数据不足";
        return '<span class="' + (gated ? "" : cls(v)) + '" style="' + (gated ? "color:#a9a293" : "") + '" title="' +
          (gated ? "该方法体系未给结论，仅列出综合价供参考" : "") + '">' + pc(v, 0) + "</span>"; } },
    { k: "disp", t: "离散度", d: 2 },
    { k: "label", t: "标签", l: 1, fmt: function (v) {
        var c = v === "低估" || v === "显著低估" ? "teal" : (v === "高估" || v === "显著高估" ? "red" : "");
        return v ? '<span class="tag ' + c + '">' + v + "</span>" : "—"; } },
    { k: "quad", t: "象限", l: 1 }
  ]);
  table($("t-valuation"), spec, rows);
}

function detail(q) {
  if (!q) return;
  var hit = BY[q] || S.filter(function (s) { return s.name && s.name.indexOf(q) >= 0 && s.composite !== null; })[0];
  if (!hit) { $("va-detail-note").textContent = "没有匹配到「" + q + "」，试试 6 位代码或名称片段。"; return; }
  var names = P.methods.map(function (m) { return m.id; });
  var vals = names.map(function (id) { return hit["v_" + id]; });
  $("va-detail-title").textContent = "单票十法拆解 · " + hit.name + "（" + hit.symbol + "）";
  var maxv = Math.max.apply(null, vals.filter(function (v) { return v; }).concat([hit.price])) * 1.25;
  CHART("c-va-detail", {
    grid: { left: 96, right: 54, top: 12, bottom: 26 },
    tooltip: { trigger: "axis", formatter: function (ps) {
      var p = ps[0]; return p.name + "<br>" + n(p.value, 2) + " 元（相对现价 " + ((p.value / hit.price - 1) * 100).toFixed(0) + "%）"; } },
    xAxis: { type: "value", max: maxv, axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", data: names.slice().reverse(), axisLabel: { color: C.sub, fontSize: 10 },
      axisLine: { lineStyle: { color: C.line } } },
    series: [{ type: "bar", data: vals.slice().reverse(), barWidth: "58%",
      itemStyle: { color: function (p) { var v = p.value; return v === null ? "#ddd" : (v >= hit.price ? C.teal : C.red); }, borderRadius: [0, 3, 3, 0] },
      label: { show: true, position: "right", fontSize: 10, color: C.sub,
        formatter: function (p) { return p.value === null ? "—" : n(p.value, 0); } },
      markLine: { silent: true, symbol: "none", lineStyle: { color: C.ink, width: 1.4, type: "solid" },
        data: [{ xAxis: hit.price }], label: { formatter: "现价 " + n(hit.price, 2), fontSize: 10, color: C.ink, position: "end" } } }]
  });
  var mfc = names.filter(function (id) { return hit["v_" + id]; }).length;
  $("va-detail-note").innerHTML = "<b>" + hit.sw1 + "</b> · 现价 <b class='num'>" + n(hit.price, 2) +
    "</b> · 综合价 <b class='num'>" + n(hit.composite, 2) + "</b>（" + pc(hit.upside, 0) + "，" + (hit.label || "—") + "）" +
    " · 参与方法 <b>" + n(hit.n_methods, 0) + "/" + names.length + "</b> · 离散度 " + n(hit.disp, 2) +
    "<br>PE " + n(hit.pe, 1) + "（自身三年分位 " + (hit.pe_pct === null ? "—" : (hit.pe_pct * 100).toFixed(0) + "%") + "）· PB " +
    n(hit.pb, 2) + "（分位 " + (hit.pb_pct === null ? "—" : (hit.pb_pct * 100).toFixed(0) + "%") + "）· ROE(年化) " + n(hit.roe, 1) +
    "% · Ke " + (hit.ke * 100).toFixed(2) + "% · 显性期增速 " + (hit.g1 * 100).toFixed(1) + "%" +
    (hit.implied_g !== null ? "<br><b>反向 DCF：</b>当前价格隐含 <b class='num'>" + n(hit.implied_g, 1) +
      "%</b> 的十年显性期增速（区间下界 −15%、上界 +60%，取到边界说明缺口大于区间）；历史营收 3 年复合 " + n(hit.rev_cagr3, 1) + "%、净利同比 " + n(hit.np_yoy, 1) +
      "%。隐含增速远高于历史实现值的，是在为一个还没发生的故事付钱。" : "");

  // 表格保持全量，不做隐式筛选（筛选是用户的选择）
  paintValTable();
}

/* ================= 05 策略对比 ================= */
function renderCompare() {
  var names = META.strategy_names, inter = META.inter, corr = META.corr;
  function heat(el, mat, fmt, colors, lo, hi) {
    var data = [], mx = -1e9, mn = 1e9;
    for (var i = 0; i < 6; i++) for (var j = 0; j < 6; j++) {
      var v = mat[i][j]; data.push([j, i, v]);
      if (v > mx) mx = v; if (v < mn) mn = v;
    }
    function mix(v) {
      var t = (v - (lo === undefined ? mn : lo)) / (((hi === undefined ? mx : hi) - (lo === undefined ? mn : lo)) || 1);
      t = Math.max(0, Math.min(1, t));
      var c1 = [247, 244, 234], c2 = [168, 52, 31];
      if (colors === "div") {
        // 负相关=青、0=近白、正相关=红。0 附近必须浅，
        // 否则「深色 = 数值大」的直觉会把 ρ≈0 读成强相关。
        var mid = [250, 248, 241];
        var src = t < 0.5 ? [26, 107, 98] : [168, 52, 31];
        var w = t < 0.5 ? (0.5 - t) * 2 : (t - 0.5) * 2;
        var r = Math.round(mid[0] + (src[0] - mid[0]) * w),
            g = Math.round(mid[1] + (src[1] - mid[1]) * w),
            b = Math.round(mid[2] + (src[2] - mid[2]) * w);
        return "rgb(" + r + "," + g + "," + b + ")";
      }
      var r2 = Math.round(c1[0] + (c2[0] - c1[0]) * t),
          g2 = Math.round(c1[1] + (c2[1] - c1[1]) * t),
          b2 = Math.round(c1[2] + (c2[2] - c1[2]) * t);
      return "rgb(" + r2 + "," + g2 + "," + b2 + ")";
    }
    CHART(el, {
      tooltip: { formatter: function (p) { return names[p.data[1]] + " × " + names[p.data[0]] + "：" + fmt(p.data[2]); } },
      grid: { left: 76, right: 18, top: 14, bottom: 58 },
      xAxis: { type: "category", data: names, axisLabel: { color: C.sub, fontSize: 11, rotate: 30 }, axisLine: { lineStyle: { color: C.line } }, splitArea: { show: false } },
      yAxis: { type: "category", data: names, axisLabel: { color: C.sub, fontSize: 11 }, axisLine: { lineStyle: { color: C.line } } },
      series: [{ type: "heatmap", data: data.map(function (d) {
          return { value: [d[0], d[1], d[2]], itemStyle: { color: mix(d[2]) } };
        }), label: { show: true, fontSize: 10.5,
          formatter: function (p) { return fmt(p.data.value[2]); } },
        itemStyle: { borderColor: "#fff", borderWidth: 2 } }]
    });
  }
  heat("c-cmp-inter", inter, function (v) { return v + " 只"; }, "seq", 0);
  heat("c-cmp-corr", corr, function (v) { return "ρ=" + v.toFixed(2); }, "div", -1, 1);

  var pts = S.filter(function (s) {
    return s.s_value !== null && s.s_growth !== null && isFinite(s.s_value) && isFinite(s.s_growth);
  });
  // 点数 >2k 时 ECharts 会切到渐进渲染（requestAnimationFrame 逐帧补绘），
  // 在 headless + virtual-time 下会和虚拟时钟互相等，页面直接卡死。关掉渐进渲染。
  var step2 = Math.max(1, Math.floor(pts.length / 1500));
  var sp = pts.filter(function (_, i) { return i % step2 === 0; }).map(function (s) {
    return [s.s_value, s.s_growth, s.s_momentum === null ? 50 : s.s_momentum, s.name, s.symbol];
  });
  CHART("c-cmp-quad", {
    grid: { left: 52, right: 20, top: 18, bottom: 36 },
    tooltip: { formatter: function (p) { return p.data[3] + " (" + p.data[4] + ")<br>价值 " + p.data[0].toFixed(0) + " · 成长 " + p.data[1].toFixed(0) + " · 动量 " + p.data[2].toFixed(0); } },
    xAxis: { type: "value", name: "价值分", nameTextStyle: { color: C.faint, fontSize: 10 }, min: 0, max: 100,
      axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "value", name: "成长分", nameTextStyle: { color: C.faint, fontSize: 10 }, min: 0, max: 100,
      axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: [{ type: "scatter", data: sp, progressive: 0, large: false,
      symbolSize: function (d) { return 3 + (100 - (isFinite(d[2]) ? d[2] : 50)) / 26; },
      itemStyle: { color: "rgba(42,79,124,.42)" },
      markLine: { silent: true, symbol: "none", lineStyle: { color: C.line, type: "dashed" },
        data: [{ xAxis: 50 }, { yAxis: 50 }], label: { show: false } } }]
  });
}

/* ================= 06 因子库 ================= */
var facGroup = "全部";
function renderFactors() {
  var nf2 = document.getElementById("fa-nf"); if (nf2) nf2.textContent = F.length;
  var H = P.health, keys = Object.keys(H.factors);
  var nMax = 0, nMin = 1e9;
  keys.forEach(function (k) { var m = H.factors[k].n; if (m) { nMax = Math.max(nMax, m); nMin = Math.min(nMin, m); } });
  $("fa-meta").textContent = H.n_dates + " 个月度调仓点 · " + (nMin === nMax ? "各因子同期" :
    "有效期数 " + nMin + "~" + nMax + " 期") + " · " + H.asof + " 附近 · Rank IC";
  var colors = [C.red, C.teal, C.gold, C.blue, "#7a5c9e", "#4a6b3a"];
  var dates = [];
  keys.forEach(function (k) { if (H.factors[k].dates.length > dates.length) dates = H.factors[k].dates; });
  CHART("c-fa-ic", {
    grid: { left: 50, right: 20, top: 42, bottom: 30 },
    tooltip: { trigger: "axis" },
    legend: { top: 4, left: "center", textStyle: { fontSize: 10, color: C.sub }, itemWidth: 12, itemHeight: 2 },
    xAxis: { type: "category", data: dates, axisLabel: { color: C.faint, fontSize: 9.5, interval: 3 }, axisLine: { lineStyle: { color: C.line } } },
    yAxis: { type: "value", axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: keys.map(function (k, i) {
      return { name: k, type: "line", data: H.factors[k].ic20, showSymbol: false,
        lineStyle: { width: 1.6, color: colors[i] }, emphasis: { focus: "series" } };
    })
  });
  var lay = H.momentum_layers, qk = ["Q1", "Q2", "Q3", "Q4", "Q5"];
  CHART("c-fa-layer", {
    grid: { left: 48, right: 20, top: 16, bottom: 28 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: qk, axisLabel: { color: C.sub, fontSize: 11 }, axisLine: { lineStyle: { color: C.line } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: C.faint, fontSize: 10, formatter: "{value}%" }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    series: [{ type: "bar", barWidth: "52%", data: qk.map(function (q) {
        var v = H.momentum_summary[q];
        return { value: v, itemStyle: { color: v >= H.momentum_summary.Q1 ? C.teal : C.red, borderRadius: [3, 3, 0, 0] } };
      }), label: { show: true, position: "top", fontSize: 10, color: C.sub, formatter: "{c}%" } }]
  });
  $("fa-layer-note").innerHTML = "按 12-1 动量分五组、每月调仓、" + lay.length + " 期实测。Q5（动量最强）前视 60 日均值 <b>" +
    n(H.momentum_summary.Q5, 2) + "%</b>，Q1 <b>" + n(H.momentum_summary.Q1, 2) + "%</b>，Q5−Q1 = <b style='color:" + C.red + "'>" +
    n(H.momentum_summary.Q5_Q1, 2) + "pp</b>，单调性" + (H.momentum_summary.mono ? "成立" : "不成立") + "。最强的一组不是最赚钱的一组。";

  var groups = ["全部", "价值", "成长", "质量", "周期", "动量", "风险"];
  $("seg-fac-group").innerHTML = groups.map(function (g) {
    return '<button data-g="' + g + '" class="' + (g === facGroup ? "on" : "") + '">' + g + "</button>";
  }).join("");
  $("seg-fac-group").querySelectorAll("button").forEach(function (b) {
    b.addEventListener("click", function () { facGroup = b.dataset.g; renderFactors(); });
  });
  var rows = F.filter(function (f) { return facGroup === "全部" || f.group === facGroup; }).map(function (f) {
    var h = H.factors[f.id];
    return { id: f.id, name: f.name, group: f.group, dir: f.dir > 0 ? "正向" : "反向",
      cov: f.coverage, ic: h ? h.ic20_mean : null, win: h ? h.ic20_win : null,
      n: h && h.n ? h.n : null, note: f.note || "" };
  });
  table($("t-factors"), [
    { k: "id", t: "ID", l: 1, c: "sym" }, { k: "name", t: "因子", l: 1 }, { k: "group", t: "组", l: 1 },
    { k: "dir", t: "方向", l: 1 },
    { k: "cov", t: "覆盖率", fmt: function (v) { return (v * 100).toFixed(0) + "%"; } },
    { k: "ic", t: "IC(20日)", fmt: function (v) { return v === null ? "未测" : '<span class="' + cls(v) + '">' + v.toFixed(3) + "</span>"; } },
    { k: "win", t: "IC 胜率", fmt: function (v) { return v === null ? "—" : (v * 100).toFixed(0) + "%"; } },
    { k: "n", t: "期数", fmt: function (v) { return v === null || v === undefined ? "—" : v + "/" + H.n_dates; } },
    { k: "note", t: "口径", l: 1 }
  ], rows);
}

/* ================= 07 方法与数据 ================= */
function renderMethod() {
  $("me-meta").textContent = "口径版本 v1 · 数据 " + META.asof;
  $("me-params").innerHTML = [
    ["无风险利率 rf", (META.rf * 100).toFixed(2) + "%", "10 年期国债，2026-11-04 观测"],
    ["股权风险溢价 ERP", (META.erp * 100).toFixed(1) + "%", "固定假设"],
    ["股权成本 Ke", "rf + β×ERP", "β 为 252 日 vs 等权全市场回归；区间 [8.5%, 15%]"],
    ["永续增长 g", (META.g_term * 100).toFixed(1) + "%", "不超过长期名义 GDP"],
    ["显性预测期", META.years + " 年", "增速线性衰减到 g"],
    ["有效税率", "15%", "高新技术企业口径"],
    ["债务成本 Kd", "4.0%", "用于 WACC"],
    ["分歧门槛", "行业内前 " + (100 - META.disp_pct_gate) + "%", "log(方法值/价格) 标准差的行业内分位"]
  ].map(function (r) {
    return '<div style="display:grid;grid-template-columns:130px 1fr;gap:10px;padding:7px 0;border-bottom:1px solid var(--line2);font-size:13px">' +
      '<div style="color:var(--faint)">' + r[0] + '</div><div><b class="num">' + r[1] + '</b>　<span class="notes">' + r[2] + "</span></div></div>";
  }).join("");

  $("me-data").innerHTML =
    "<p style='margin:0 0 8px'><b>财务</b>：全市场 PIT 面板，12 个报告期（2023-12-31 ~ 2026-09-30），按公告日生效（available_at），" +
    "无未来函数。字段含营收、净利、经营现金流、总资产/负债、权益、EPS/BPS/OCFPS、ROE、毛利率、同比。" +
    "单位：比率字段为百分数（15.6 = 15.6%），利润表为元。</p>" +
    "<p style='margin:0 0 8px'><b>行情</b>：本地日线库（后复权，3,500+ 只），加上当日未复权收盘快照，用于真实价格、市值、动量与估值历史带。" +
    "停牌日以零成交行存在，横截面一律先过滤 volume&gt;0。</p>" +
    "<p style='margin:0 0 8px'><b>行业</b>：申万一级时点分类（5,884 条），按生效区间关联，不回填最新分类。</p>" +
    "<p style='margin:0 0 8px'><b>股息</b>：年度股息率与股利支付率来自高股息样本（" + n(META.n_div_cohort, 0) + " 只，股息率 ≥4%），" +
    "DDM 与红利策略只在这批股票上有结论。</p>" +
    "<p style='margin:0'><b>更新</b>：截止日由本地行情库最后一根 K 线推导（当前 " + META.asof + "），不手工改日期；" +
    "每个交易日收盘后重跑，横截面固化成快照，于是 08 页能对比前后两日。" +
    "价格是双来源：本地 K 线（3,500+ 只）与当日快照（5,200+ 只），只在快照日期等于截止日时使用快照，" +
    "并校验两边同日价格一致（本期重叠样本偏差中位 0.000%）。</p>";

  var fml = [
    ["相对行业 PE", "价值 = EPS_ttm × 行业中位 PE"],
    ["相对行业 PB", "价值 = BPS × 行业中位 PB"],
    ["自身历史 PE/PB", "价值 = EPS_ttm × 自身三年月度 PE 中位数"],
    ["DCF (FCFE)", "FCFE₀ = EPS×(1−再投资率)，十年两阶段，Ke 折现"],
    ["DCF (FCFF)", "FCFF₀ = EBIT×(1−t)×(1−再投资率)，WACC 折现"],
    ["DDM", "V = DPS×(1+g)/(Ke−g)，要求 Ke−g ≥ 3pp"],
    ["EPV", "V = EBIT×(1−t)/WACC（零增长价值）"],
    ["PEG", "V = EPS × clip(3年净利复合增速, 8, 45)"],
    ["剩余收益 RI", "V = BPS + Σ(ROE−Ke)×B/(1+Ke)ᵗ + 终值"]
  ];
  $("me-formula").innerHTML = fml.map(function (r) {
    return '<div style="display:grid;grid-template-columns:96px 1fr;gap:10px;padding:6px 0;border-bottom:1px solid var(--line2);font-size:12.5px">' +
      '<div style="color:var(--faint)">' + r[0] + '</div><div class="mono" style="font-size:12px">' + r[1] + "</div></div>";
  }).join("");

  $("me-rules").innerHTML =
    "<p style='margin:0 0 6px'>• PE 类：EPS_ttm &gt; 0 且 0 &lt; PE ≤ 150</p>" +
    "<p style='margin:0 0 6px'>• DCF(FCFE)：ROE(年化) &gt; 6% 且 3 年营收复合在 [−10%, 40%]</p>" +
    "<p style='margin:0 0 6px'>• DCF(FCFF)/EPV：非金融、EBIT &gt; 0、3 年营收复合在 [−25%, 45%]</p>" +
    "<p style='margin:0 0 6px'>• DDM：可观测 DPS &gt; 0 且派息率 ≤ 90% 且 Ke−g ≥ 3pp</p>" +
    "<p style='margin:0 0 6px'>• PEG：3 年净利复合在 [5%, 50%]</p>" +
    "<p style='margin:0 0 6px'>• RI：BPS &gt; 0 且 ROE 在 [2%, 40%]</p>" +
    "<p style='margin:0 0 6px'>• 综合价 = 可用方法的加权中位数（对数空间），避免单一模型带偏</p>" +
    "<p style='margin:0'>• 标签：≥2 方法且离散度不在行业内前 " + (100 - META.disp_pct_gate) + "% 才给结论；上涨空间 ≥60% 显著低估、25–60% 低估、±25% 合理、−25%~−55% 高估、≤−55% 显著高估</p>";

  $("me-traps").innerHTML =
    "<p style='margin:0 0 8px'><b>1. Ke 是最大的杠杆。</b>Ke 从 8.5% 提到 10%，DCF 类价值平均下滑 15–25%。这不是精度问题，是假设问题。" +
    "绝对法系统性低于市价，所以全市场标签偏「高估」——跨股票比较请优先看同行业相对位置。</p>" +
    "<p style='margin:0 0 8px'><b>2. 季报累计口径。</b>ROE、EPS 为年初至今累计值，跨期比较必须年化（roe×4/季度数）或与自己同季对比。平台已年化，但 3 年复合用年报口径。</p>" +
    "<p style='margin:0 0 8px'><b>3. 量价因子只覆盖有本地日线的股票。</b>约 3,300 只有 250 日以上历史，新上市与部分北交所股票动量分为空——它们不会进入动量榜，但也不会被当成 0 分。</p>" +
    "<p style='margin:0 0 8px'><b>4. 银行/保险不做 DCF。</b>经营现金流与资本开支对金融企业没有意义，只保留 PE/PB/RI/DDM 四类。" +
    "同理，重资产周期股在盈利顶部 PE 最低，价值策略因此加入 EPV 与 EBIT/EV 做交叉。</p>" +
    "<p style='margin:0 0 8px'><b>5. 动量是失效的，而且有时是反向的。</b>" + P.health.n_dates + " 个调仓点上 12-1 动量 IC 均值 " +
    n(P.health.factors.MOM_12_1.ic20_mean, 3) + "、胜率 " + n(P.health.factors.MOM_12_1.ic20_win * 100, 0) +
    "%。不要因为「动量策略有榜单」就以为它有效——榜单本身不是证据。</p>" +
    "<p style='margin:0 0 8px'><b>6. 股息样本偏高分位。</b>DDM 只在股息率 ≥4% 的 " + n(META.n_div_cohort, 0) +
    " 只上有值，这意味着低股息股票的综合价不含 DDM 意见，方法数天然更少——方法数是覆盖度指标，不是质量指标。</p>" +
    "<p style='margin:0'><b>7. 不处理交易成本、流动性、涨跌停与停牌。</b>榜单是候选池，不是可执行组合。</p>";

  var H = P.health, keys = Object.keys(H.factors);
  var icv = keys.map(function (k) { return H.factors[k].ic20_mean; });
  var lim = 0;
  icv.forEach(function (v) { if (v !== null && Math.abs(v) > lim) lim = Math.abs(v); });
  lim = Math.max(0.02, lim * 1.45);
  var icLab = { show: true, fontSize: 9.5, color: C.sub, distance: 5,
    formatter: function (p) { return p.value === null || p.value === undefined ? "" : p.value.toFixed(4); } };
  CHART("c-me-health", {
    grid: { left: 76, right: 58, top: 12, bottom: 26 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", min: -lim, max: lim,
      axisLabel: { color: C.faint, fontSize: 10, formatter: function (v) { return v.toFixed(2); } },
      splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", data: keys, axisLabel: { color: C.sub, fontSize: 10.5 },
      axisLine: { lineStyle: { color: C.line } } },
    series: [
      { type: "bar", barGap: "-100%", barWidth: "56%",
        data: icv.map(function (v) { return v >= 0 ? v : null; }),
        itemStyle: { color: C.teal, borderRadius: [0, 3, 3, 0] },
        label: Object.assign({}, icLab, { position: "right" }) },
      { type: "bar", barGap: "-100%", barWidth: "56%",
        data: icv.map(function (v) { return v < 0 ? v : null; }),
        itemStyle: { color: C.red, borderRadius: [3, 0, 0, 3] },
        label: Object.assign({}, icLab, { position: "left" }) }
    ]
  });
  table($("t-health"), [
    { k: "k", t: "因子", l: 1 }, { k: "ic20", t: "IC(20日)", fmt: function (v) { return v === null ? "—" : v.toFixed(4); } },
    { k: "win", t: "胜率", fmt: function (v) { return v === null ? "—" : (v * 100).toFixed(0) + "%"; } },
    { k: "ic60", t: "IC(60日)", fmt: function (v) { return v === null ? "—" : v.toFixed(4); } },
    { k: "win60", t: "胜率60", fmt: function (v) { return v === null ? "—" : (v * 100).toFixed(0) + "%"; } },
    { k: "n", t: "有效期数", fmt: function (v) { return v === null || v === undefined ? "—" : v + "/" + H.n_dates; } },
    { k: "verdict", t: "结论", l: 1 }
  ], keys.map(function (k) {
    var h = H.factors[k];
    var v = h.ic20_mean;
    var verdict = v === null ? "未测" : (v > 0.03 ? "有效" : v > 0 ? "弱正" : v > -0.03 ? "基本无效" : "反向（勿用）");
    return { k: k, ic20: h.ic20_mean, win: h.ic20_win, ic60: h.ic60_mean, win60: h.ic60_win,
      n: h.n === undefined ? null : h.n, verdict: verdict };
  }));
}

/* ================= 路由 ================= */
/* ================= 08 今日变化 ================= */
var dfBoard = "上涨空间";

function dfHeat(el, mat, labels) {
  var data = [], mx = 1;
  for (var i = 0; i < labels.length; i++) for (var j = 0; j < labels.length; j++) {
    var v = (mat[i] && mat[i][j]) || 0;
    data.push([j, i, v]);
    if (v > mx) mx = v;
  }
  function mix(v) {
    var t = Math.min(1, Math.sqrt(v / mx));
    var c1 = [250, 248, 241], c2 = [26, 107, 98];
    return "rgb(" + Math.round(c1[0] + (c2[0] - c1[0]) * t) + "," +
      Math.round(c1[1] + (c2[1] - c1[1]) * t) + "," +
      Math.round(c1[2] + (c2[2] - c1[2]) * t) + ")";
  }
  CHART(el, {
    tooltip: { formatter: function (p) {
      var d = p.data.value;
      return labels[d[1]] + " → " + labels[d[0]] + "：" + d[2] + " 只";
    } },
    grid: { left: 84, right: 16, top: 14, bottom: 76 },
    xAxis: { type: "category", data: labels,
      axisLabel: { color: C.sub, fontSize: 10, rotate: 34 }, axisLine: { lineStyle: { color: C.line } } },
    yAxis: { type: "category", data: labels,
      axisLabel: { color: C.sub, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
    series: [{ type: "heatmap", data: data.map(function (d) {
        return { value: [d[0], d[1], d[2]], itemStyle: { color: mix(d[2]) } };
      }),
      label: { show: true, fontSize: 9.5, color: C.ink,
        formatter: function (p) { return p.data.value[2] ? p.data.value[2] : ""; } },
      itemStyle: { borderColor: "#fff", borderWidth: 1.5 } }]
  });
}

function renderDiff() {
  var D = P.diff || {};
  var meta = $("df-meta"), kpi = $("df-kpi");
  if (D.first || !D.prev) {
    meta.textContent = "首日无对比基线";
    kpi.innerHTML = '<div class="card" style="grid-column:1/-1">' +
      '<div class="eyebrow">还没有可对比的上一交易日</div>' +
      '<div class="notes" style="margin-top:8px">今日快照已固化（' + (D.cur || META.asof) +
      '，' + n(META.n_universe, 0) + ' 只）。等下一个交易日跑完，这里会出现标签迁移、榜单进出与位移榜。' +
      '日更的价值在 diff，不在重算——所以第一天什么都没有是正常的。</div></div>';
    return;
  }
  meta.textContent = D.prev + " → " + D.cur + " · 可比 " + n(D.n_comp || D.n_overlap, 0) + " 只（两日都有估值结论）";

  var mv = D.moves || {};
  var mdd = mv.med_d === null || mv.med_d === undefined ? null : mv.med_d;
  kpi.innerHTML = [
    ["可比样本", n(D.n_comp || D.n_overlap, 0), "两日都有估值结论"],
    ["上涨空间上移", n(mv.up, 0), "变化 > +2pp"],
    ["下移", n(mv.down, 0), "变化 < −2pp"],
    ["中位位移", mdd === null ? "—" : (mdd > 0 ? "+" : "") + (mdd * 100).toFixed(1) + "%",
      "全样本上涨空间中位"]
  ].map(function (x) {
    return '<div class="card kpi"><div class="k">' + x[0] + '</div><div class="v">' + x[1] +
      '</div><div class="s">' + x[2] + "</div></div>";
  }).join("");

  // 覆盖不足提示：上一交易日若是回补（缺历史 K 线），可比样本会明显少于今日
  var pv = D.pool_prev || 0, cv = D.pool_cur || 0;
  var note = document.getElementById("df-cov");
  if (note) {
    note.innerHTML = (pv && cv && pv < cv * 0.9)
      ? "<b>注意：</b>上一交易日只有 " + n(pv, 0) + " 只给出估值结论，今日 " + n(cv, 0) +
        " 只。本页所有对比都只用「两日都有结论」的 " + n(D.n_comp, 0) +
        " 只，因此不会把覆盖变化误读成标签迁移。"
      : "两日覆盖接近（" + n(pv, 0) + " / " + n(cv, 0) + " 只），对比样本 " + n(D.n_comp, 0) + " 只。";
  }

  dfHeat("c-df-mat", D.matrix || [], D.labels || LBL_ORDER);

  // 标签净变化：正负分两个系列，标签才落在柱子外侧
  var net = (D.net || []).slice().sort(function (a, b) { return a.d - b.d; });
  var nv = net.map(function (x) { return x.d; });
  var lim = 0; nv.forEach(function (v) { if (Math.abs(v) > lim) lim = Math.abs(v); });
  lim = Math.max(10, lim * 1.5);
  var netLab = { show: true, fontSize: 9.5, color: C.sub, distance: 4,
    formatter: function (p) {
      if (p.value === null || p.value === undefined) return "";
      return (p.value > 0 ? "+" : "") + p.value;
    } };
  CHART("c-df-net", {
    grid: { left: 76, right: 44, top: 12, bottom: 24 },
    tooltip: { formatter: function (ps) {
      var p = ps[0] || ps, x = net[p.dataIndex];
      return x.k + "<br>昨日 " + x.a + " → 今日 " + x.b;
    } },
    xAxis: { type: "value", min: -lim, max: lim,
      axisLabel: { color: C.faint, fontSize: 10 }, splitLine: { lineStyle: { color: "#f0eee7" } } },
    yAxis: { type: "category", data: net.map(function (x) { return x.k; }),
      axisLabel: { color: C.sub, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
    series: [
      { type: "bar", barGap: "-100%", barWidth: "56%",
        data: nv.map(function (v) { return v >= 0 ? v : null; }),
        itemStyle: { color: C.teal, borderRadius: [0, 3, 3, 0] },
        label: Object.assign({}, netLab, { position: "right" }) },
      { type: "bar", barGap: "-100%", barWidth: "56%",
        data: nv.map(function (v) { return v < 0 ? v : null; }),
        itemStyle: { color: C.red, borderRadius: [3, 0, 0, 3] },
        label: Object.assign({}, netLab, { position: "left" }) }
    ]
  });

  table($("t-df-shift"), [
    { k: "s", t: "代码", l: 1, c: "sym" }, { k: "n", t: "名称", l: 1 },
    { k: "a", t: "昨日", fmt: function (v) { return v === null ? "—" : (v * 100).toFixed(1) + "%"; } },
    { k: "b", t: "今日", fmt: function (v) { return v === null ? "—" : (v * 100).toFixed(1) + "%"; } },
    { k: "d", t: "位移", fmt: function (v) {
      return v === null ? "—" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : "") + (v * 100).toFixed(1) + "pp</span>";
    } },
    { k: "la", t: "昨日标签", l: 1 }, { k: "lb", t: "今日标签", l: 1 }
  ], D.shift || []);

  // 榜单进出
  var boards = D.boards || [];
  $("seg-df-board").innerHTML = boards.map(function (b) {
    return '<button data-b="' + b.name + '" class="' + (b.name === dfBoard ? "on" : "") + '">' + b.name + "</button>";
  }).join("");
  $("seg-df-board").querySelectorAll("button").forEach(function (btn) {
    btn.addEventListener("click", function () { dfBoard = btn.dataset.b; renderDiff(); });
  });
  var cur = boards.filter(function (b) { return b.name === dfBoard; })[0] || boards[0] || { in: [], out: [] };
  $("df-in-note").textContent = "新进 Top50 · " + n(cur.n_in, 0) + " 只";
  $("df-out-note").textContent = "跌出 Top50 · " + n(cur.n_out, 0) + " 只";
  var bspec = [
    { k: "s", t: "代码", l: 1, c: "sym" }, { k: "n", t: "名称", l: 1 },
    { k: "v", t: dfBoard === "上涨空间" ? "上涨空间" : "分数", fmt: function (v) {
      if (v === null || v === undefined) return "—";
      return dfBoard === "上涨空间" ? (v * 100).toFixed(1) + "%" : n(v, 1);
    } }
  ];
  table($("t-df-in"), bspec, cur["in"] || []);
  table($("t-df-out"), bspec, cur.out || []);
}

var TABS = [
  ["home", "首页"], ["overview", "01 市场总览"], ["strategy", "02 策略中心"],
  ["screener", "03 选股器"], ["valuation", "04 个股估值"], ["compare", "05 策略对比"],
  ["factors", "06 因子库"], ["method", "07 方法与数据"], ["diff", "08 今日变化"]
];
var RENDER = { home: renderHome, overview: renderOverview, strategy: renderStrategy,
  screener: renderScreener, valuation: renderValuation, compare: renderCompare,
  factors: renderFactors, method: renderMethod, diff: renderDiff };
var done = {};

function go(tab) {
  if (!RENDER[tab]) tab = "home";
  document.querySelectorAll("section.view").forEach(function (s) { s.classList.remove("on"); });
  var el = $("v-" + tab);
  if (el) el.classList.add("on");
  document.querySelectorAll("#nav .tab-btn").forEach(function (b) {
    b.classList.toggle("on", b.dataset.t === tab);
  });
  if (!done[tab]) { try { RENDER[tab](); done[tab] = 1; } catch (e) { console.error(tab, e); } }
  else {
    // 重新激活时让图表 resize（隐藏容器宽度为 0，init 会等到可见）
    setTimeout(function () {
      document.querySelectorAll("#v-" + tab + " .chart").forEach(function (d) {
        var inst = window.echarts && window.echarts.getInstanceByDom(d);
        if (inst) try { inst.resize(); } catch (e) {}
      });
    }, 60);
  }
  window.scrollTo({ top: 0, behavior: "instant" });
  if (location.hash.slice(1) !== tab) history.replaceState(null, "", "#" + tab);
}

(function () {
  var fa = document.getElementById("foot-asof"), fr = document.getElementById("foot-rp");
  if (fa) fa.textContent = META.asof || "—";
  var ha = document.getElementById("hero-asof");
  if (ha) ha.textContent = META.asof || "—";
  if (fr) {
    var q = String(META.report_period || "");
    fr.textContent = q ? q.slice(0, 4) + " 年" + (q.slice(5) === "1" ? "一" : q.slice(5) === "2" ? "二" : q.slice(5) === "3" ? "三" : "四") + "季报" : "—";
  }
})();

$("nav").innerHTML = TABS.map(function (t) {
  return '<button class="tab-btn" data-t="' + t[0] + '">' + t[1] + "</button>";
}).join("");
document.querySelectorAll("#nav .tab-btn, [data-go]").forEach(function (b) {
  b.addEventListener("click", function () { go(b.dataset.t || b.dataset.go); });
});
$("bigbtn").addEventListener("click", function () {
  document.body.classList.toggle("big");
  this.textContent = document.body.classList.contains("big") ? "标准版" : "大字版";
  localStorage.setItem("panorama_big", document.body.classList.contains("big") ? "1" : "");
});
if (localStorage.getItem("panorama_big")) { document.body.classList.add("big"); $("bigbtn").textContent = "标准版"; }

go((location.hash || "#home").slice(1) || "home");
})();
