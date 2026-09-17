// 明账 ClearLedger — 应用骨架：路由 / 顶栏 / 公共格式化 / 轮询管理
window.Pages = {};

const Fmt = {
  wan(v) {
    if (v === null || v === undefined) return '—';
    return (v / 1e4).toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' 万';
  },
  yuan(v) {
    if (v === null || v === undefined) return '—';
    return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  },
  pct(v) {
    if (v === null || v === undefined) return '—';
    return (v * 100).toFixed(1) + '%';
  },
  signedPct(v) {
    if (v === null || v === undefined) return '—';
    const s = (v * 100).toFixed(1) + '%';
    return v > 0 ? '↑ ' + s : (v < 0 ? '↓ ' + s : '→ ' + s);
  },
  dt(s) { return s ? String(s).replace('T', ' ') : '—'; },
  dur(sec) {
    if (sec === null || sec === undefined) return '—';
    if (sec < 60) return sec.toFixed(1) + ' 秒';
    return Math.floor(sec / 60) + ' 分 ' + Math.round(sec % 60) + ' 秒';
  },
  runDur(r) {
    if (!r || !r.started_at || !r.finished_at) return '—';
    const a = new Date(r.started_at), b = new Date(r.finished_at);
    return Fmt.dur((b - a) / 1000);
  },
};

const LIGHT_LABEL = { green: '正常', yellow: '数据告警', red: '跑批失败', unknown: '未跑批', running: '跑批中' };
const Light = {
  html(st) { return `<span class="light light-${st}"><i></i>${LIGHT_LABEL[st] || st}</span>`; },
};
const STATUS_LABEL = {
  success: '成功', pass: '通过', warn: '告警', error: '错误', fail: '失败',
  skipped: '跳过', 'not_run': '未执行', 'runtime error': '运行错误', unknown: '未知',
};
const StChip = {
  html(st) { return `<span class="status-chip st-${String(st).replace(' ', '-')}">${STATUS_LABEL[st] || st}</span>`; },
};
const DOT_CLASS = { green: 'dot-green', yellow: 'dot-yellow', red: 'dot-red',
  success: 'dot-green', pass: 'dot-green', warn: 'dot-yellow', error: 'dot-red',
  fail: 'dot-red', skipped: 'dot-skip', 'not_run': 'dot-skip', 'runtime error': 'dot-red', unknown: 'dot-gray' };

const App = {
  charts: [],   // 已注册的 echarts 实例（切页时销毁）
  graph: null,  // g6 实例
  polls: [],    // 定时轮询句柄
  sysTimer: null,

  NAV: [
    { key: 'overview', label: '总览', ico: '◎' },
    { key: 'lineage', label: '数据血缘', ico: '⛓' },
    { key: 'dictionary', label: '数据字典', ico: '📖' },
    { key: 'reports', label: '管理报表', ico: '▤' },
    { key: 'runs', label: '跑批历史', ico: '⟳' },
  ],

  init() {
    document.getElementById('foot-version').textContent = '早航版 · 私有化部署';
    this.buildNav();
    window.addEventListener('hashchange', () => this.route());
    document.getElementById('btn-run').addEventListener('click', () => this.triggerRun());
    this.refreshSys();
    this.sysTimer = setInterval(() => this.refreshSys(), 60_000);
    this.route();
  },

  buildNav() {
    const nav = document.getElementById('nav');
    nav.innerHTML = this.NAV.map(n =>
      `<a href="#/${n.key}" data-key="${n.key}"><span class="ico">${n.ico}</span>${n.label}</a>`
    ).join('');
  },

  route() {
    this.cleanup();
    const raw = (location.hash || '#/overview').replace(/^#\//, '');
    const [key, ...rest] = raw.split('/');
    const page = window.Pages[key] || window.Pages.overview;
    document.querySelectorAll('#nav a').forEach(a =>
      a.classList.toggle('active', a.dataset.key === (window.Pages[key] ? key : 'overview')));
    const container = document.getElementById('page');
    container.innerHTML = '<div class="empty-tip">加载中…</div>';
    document.getElementById('page-title').textContent =
      (this.NAV.find(n => n.key === (window.Pages[key] ? key : 'overview')) || {}).label || '总览';
    page.render(container, rest.join('/'));
  },

  cleanup() {
    this.charts.forEach(c => { try { c.dispose(); } catch (_) {} });
    this.charts = [];
    if (this.graph) { try { this.graph.destroy(); } catch (_) {} this.graph = null; }
    this.polls.forEach(t => clearInterval(t));
    this.polls = [];
  },

  chart(el, option) {
    const inst = echarts.init(el);
    inst.setOption(option);
    window.addEventListener('resize', () => inst.resize());
    this.charts.push(inst);
    return inst;
  },

  // ---------- 顶栏系统状态 ----------
  async refreshSys() {
    try {
      const ov = await api('/api/overview');
      const st = ov.running && ov.running.active ? 'running' : ov.light;
      document.getElementById('sys-light').innerHTML = Light.html(st);
      const lr = ov.last_run;
      document.getElementById('sys-runinfo').textContent = lr
        ? `上次跑批 ${Fmt.dt(lr.finished_at)} · 下次 ${ov.schedule.label}`
        : `尚未跑批 · 计划 ${ov.schedule.label}`;
    } catch (_) { /* 静默：页面内已有错误提示 */ }
  },

  async triggerRun() {
    const btn = document.getElementById('btn-run');
    try {
      const r = await api('/api/runs/trigger', { method: 'POST' });
      Toast.show('跑批已启动：' + r.run_id);
    } catch (_) { return; }
    btn.disabled = true; btn.textContent = '⟳ 跑批中…';
    document.getElementById('sys-light').innerHTML = Light.html('running');
    const timer = setInterval(async () => {
      try {
        const st = await api('/api/runs/status');
        if (!st.active) {
          clearInterval(timer);
          btn.disabled = false; btn.textContent = '▶ 立即跑批';
          this.refreshSys();
          Toast.show('跑批结束');
          if (location.hash.startsWith('#/runs') || location.hash.startsWith('#/overview')) this.route();
        }
      } catch (_) { clearInterval(timer); btn.disabled = false; btn.textContent = '▶ 立即跑批'; }
    }, 3000);
  },

  // ---------- 轮询 ----------
  poll(fn, ms) { const t = setInterval(fn, ms); this.polls.push(t); return t; },

  // ---------- 通用 DOM ----------
  el(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  },
};
