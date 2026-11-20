/* chart-boot.js — 单文件离线报告的图表引导层
 *
 * 用法：在页面里引入本文件（build_report.py 会把它内联进 HTML），
 *       然后每张图写成 CHART('chart1', option1);
 *
 * 它一次性处理四类"图表空白"故障：
 *   1. 图表库没加载（CDN 不可达 / 断网 / 预览器屏蔽外链）→ 容器内显示可读提示，而不是白板
 *   2. 容器宽度或高度为 0 时初始化（隐藏标签页、异步布局）→ 等布局就绪再 init
 *   3. 某一个 option 写错导致后续所有图表连带失败 → 每张图独立 try/catch
 *   4. 窗口或容器尺寸变化后不自适应 → resize + ResizeObserver，带防抖
 */
(function () {
  'use strict';

  var mounted = [];
  var pending = [];
  var chartIds = [];
  var lastWidth = -1;

  function fallback(el, title, hint) {
    el.innerHTML =
      '<div style="height:100%;min-height:120px;display:flex;flex-direction:column;' +
      'align-items:center;justify-content:center;padding:16px;text-align:center;' +
      'font-size:12.5px;line-height:1.7;color:#8a4b3a;background:#fdf6f4;' +
      'border:1px dashed #e0b9ae;border-radius:8px;box-sizing:border-box;">' +
      '<div style="font-weight:600;margin-bottom:4px;">' + title + '</div>' +
      '<div style="color:#6b7684;max-width:520px;">' + hint + '</div></div>';
  }

  function safeResize(inst) {
    try { inst.resize(); } catch (e) { /* ignore */ }
  }

  function mount(id, option) {
    var el = document.getElementById(id);
    if (!el) {
      console.warn('[chart-boot] 容器不存在: #' + id);
      return;
    }
    if (typeof window.echarts === 'undefined') {
      fallback(el, '图表库未加载',
        '这份 HTML 没有内联 echarts.min.js。请用 build_report.py 重新构建，' +
        '不要引用 CDN 或相对路径脚本。');
      return;
    }
    if (!el.clientWidth || !el.clientHeight) {
      var n = (el.__chartWait || 0) + 1;
      el.__chartWait = n;
      if (n <= 90) {
        window.requestAnimationFrame(function () { mount(id, option); });
        return;
      }
      fallback(el, '图表容器尺寸为 0',
        '请给 #' + id + ' 设置显式高度（例如 .chart{height:360px}），' +
        '并确认它没有被父级 display:none 隐藏。');
      return;
    }
    el.__chartWait = 0;
    var inst = window.echarts.getInstanceByDom(el);
    if (!inst) {
      inst = window.echarts.init(el, null, { renderer: 'canvas' });
    }
    try {
      inst.setOption(option, true);
    } catch (err) {
      console.error('[chart-boot] #' + id + ' 配置错误', err);
      fallback(el, '图表 #' + id + ' 配置错误',
        String((err && err.message) || err));
      return;
    }
    if (mounted.indexOf(inst) < 0) { mounted.push(inst); }
    if (chartIds.indexOf(id) < 0) { chartIds.push(id); }
  }

  window.CHART = function (id, option) {
    if (document.readyState === 'loading') {
      pending.push([id, option]);
    } else {
      mount(id, option);
    }
  };

  window.CHART_RESIZE = function (id) {
    if (!window.echarts) { return; }
    var el = document.getElementById(id);
    if (!el) { return; }
    var inst = window.echarts.getInstanceByDom(el);
    if (inst) { safeResize(inst); }
  };

  window.CHART_RESIZE_ALL = function () {
    if (!window.echarts) { return; }
    chartIds.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || el.offsetParent === null) { return; }
      var inst = window.echarts.getInstanceByDom(el);
      if (inst) { safeResize(inst); }
    });
  };

  function flush() {
    var q = pending.splice(0, pending.length);
    for (var i = 0; i < q.length; i++) { mount(q[i][0], q[i][1]); }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', flush);
  } else {
    flush();
  }

  window.addEventListener('load', function () {
    window.setTimeout(function () {
      window.CHART_RESIZE_ALL();
      lastWidth = document.documentElement.clientWidth;
    }, 50);
  });

  var resizeTimer;
  window.addEventListener('resize', function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      window.CHART_RESIZE_ALL();
      lastWidth = document.documentElement.clientWidth;
    }, 120);
  });

  if (typeof window.ResizeObserver === 'function') {
    var ro = new window.ResizeObserver(function () {
      var w = document.documentElement.clientWidth;
      if (w === lastWidth) { return; }
      lastWidth = w;
      window.setTimeout(window.CHART_RESIZE_ALL, 120);
    });
    ro.observe(document.documentElement);
  }
})();
