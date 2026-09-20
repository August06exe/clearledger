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

// 线性图标（feather 风格，stroke: currentColor，随导航文字变色）
const ICON_SVG = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  lineage: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
  dictionary: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  reports: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
  runs: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  workbench: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  ai: '<rect x="5" y="8" width="14" height="10" rx="2"/><circle cx="9.5" cy="13" r="1.1" fill="currentColor" stroke="none"/><circle cx="14.5" cy="13" r="1.1" fill="currentColor" stroke="none"/><path d="M12 8V5.5"/><circle cx="12" cy="4" r="1"/><path d="M9 18v2M15 18v2"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_SVG[name] || ''}</svg>`;

const App = {
  charts: [],   // 已注册的 echarts 实例（切页时销毁）
  ALIASES: { nodes: {}, fields: {} },  // 界面中文化别名（/api/aliases）
  graph: null,  // g6 实例
  polls: [],    // 定时轮询句柄
  sysTimer: null,

  NAV: [
    { key: 'overview', label: '总览' },
    { key: 'lineage', label: '数据血缘' },
    { key: 'dictionary', label: '数据字典' },
    { key: 'reports', label: '管理报表' },
    { key: 'runs', label: '跑批历史' },
    { key: 'workbench', label: '配置工作台' },
    { key: 'ai', label: 'AI 接入' },
  ],

  init() {
    document.getElementById('foot-version').textContent = '早航版 · 私有化部署';
    this.buildNav();
    window.addEventListener('hashchange', () => this.route());
    document.getElementById('btn-run').addEventListener('click', () => this.triggerRun());
    document.getElementById('btn-sched').addEventListener('click', () => this.openSchedModal());
    document.getElementById('inst-select').addEventListener('change', async e => {
      try {
        await api('/api/instance', { method: 'POST', body: JSON.stringify({ instance: e.target.value }) });
        Toast.show('已切换账套：' + e.target.selectedOptions[0].text);
        this.route();          // 当前页按新账套重渲染
      } catch (_) { this.refreshSys(); }
    });
    this.refreshSys();
    this.sysTimer = setInterval(() => this.refreshSys(), 60_000);
    this.loadAliases();
    this.maybeAiBanner();
    this.route();
  },

  // ---------- 首开 AI 接入提醒横幅（开关在 AI 接入页） ----------
  async maybeAiBanner() {
    if (document.getElementById('ai-banner')) return;
    let s = {};
    try { s = await api('/api/settings'); } catch (_) { return; }
    if (s.ai_banner === false) return;
    const banner = this.el(`
      <div id="ai-banner">
        <span class="ai-banner-ico">🤖</span>
        <div class="ai-banner-text">
          <b>明账是 AI-Native 的</b>——配置与管道的搭建维护，都交给 agent 伺候。
          <a href="#/ai">看看如何让你的 agent 介入 →</a>
        </div>
        <label class="ai-banner-check" title="保存后，下次打开门户不再显示">
          <input type="checkbox" id="ai-banner-off">下次不再提醒
        </label>
        <button class="ai-banner-x" id="ai-banner-close" title="本次关闭">×</button>
      </div>`);
    document.getElementById('main').prepend(banner);
    banner.querySelector('#ai-banner-off').addEventListener('change', async e => {
      try {
        await api('/api/settings', { method: 'POST', body: JSON.stringify({ ai_banner: !e.target.checked }) });
      } catch (_) { e.target.checked = !e.target.checked; }
    });
    banner.querySelector('#ai-banner-close').addEventListener('click', () => banner.remove());
  },

  async loadAliases() {
    try { this.ALIASES = await api('/api/aliases'); } catch (_) {}
  },

  // 技术名 → 中文（查不到返回原名）
  alias(name) {
    if (!name) return name;
    return this.ALIASES.nodes[name] || name;
  },
  falias(field) {
    if (!field) return field;
    return this.ALIASES.fields[field] || field;
  },

  async refreshInstances(selected) {
    try {
      const data = await api('/api/instance');
      const sel = document.getElementById('inst-select');
      const cur = selected || data.current;
      sel.innerHTML = data.instances.map(i =>
        `<option value="${i.name}" ${i.name === cur ? 'selected' : ''}>🏷 ${i.title}</option>`).join('');
    } catch (_) {}
  },

  buildNav() {
    const nav = document.getElementById('nav');
    nav.innerHTML = this.NAV.map(n =>
      `<a href="#/${n.key}" data-key="${n.key}"><span class="ico">${icon(n.key)}</span>${n.label}</a>`
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
      this.refreshInstances(ov.instance && ov.instance.name);
      if (ov.instance) {
        document.getElementById('page-title').textContent =
          (this.NAV.find(n => n.key === this.currentKey()) || {}).label + '';
      }
      const st = ov.running && ov.running.active ? 'running' : ov.light;
      document.getElementById('sys-light').innerHTML = Light.html(st);
      const s = ov.schedule || {};
      const schedTxt = s.schedule_enabled
        ? `自动 ${String(s.schedule_hour).padStart(2, '0')}:${String(s.schedule_minute).padStart(2, '0')}`
        : '手动模式';
      const lr = ov.last_run;
      const instName = ov.instance ? `【${ov.instance.title}】` : '';
      document.getElementById('sys-runinfo').textContent = lr
        ? `${instName}上次跑批 ${Fmt.dt(lr.finished_at)} · ${schedTxt}`
        : `${instName}尚未跑批 · ${schedTxt}`;
    } catch (_) { /* 静默：页面内已有错误提示 */ }
  },

  currentKey() {
    const raw = (location.hash || '#/overview').replace(/^#\//, '');
    const key = raw.split('/')[0];
    return window.Pages[key] ? key : 'overview';
  },

  // ---------- 跑批设置弹窗 ----------
  async openSchedModal() {
    const old = document.getElementById('modal-overlay');
    if (old) old.remove();
    let s = {};
    try { s = await api('/api/settings'); } catch (_) { return; }
    const hh = String(s.schedule_hour).padStart(2, '0');
    const mm = String(s.schedule_minute).padStart(2, '0');
    const overlay = this.el(`
      <div id="modal-overlay">
        <div class="modal card">
          <h3>⏰ 跑批设置</h3>
          <label class="row" style="gap:8px;margin:16px 0 10px;font-size:14px">
            <input type="checkbox" id="sch-en" ${s.schedule_enabled ? 'checked' : ''}>
            每天定时自动跑批
          </label>
          <div style="margin-bottom:14px" class="muted">
            开启后每天 <input type="time" id="sch-time" value="${hh}:${mm}"> 自动出数（T+1），
            关机错过了会在开机后自动补跑。
          </div>
          <div style="margin-bottom:14px" class="muted">
            关闭即<strong>完全手动</strong>：只有点"▶ 立即跑批"才会跑，不会有任何自动动作。
          </div>
          <div class="row" style="justify-content:flex-end;margin-top:16px">
            <button class="btn" id="sch-cancel">取消</button>
            <button class="btn btn-primary" id="sch-save">保存</button>
          </div>
        </div>
      </div>`);
    document.body.appendChild(overlay);
    const syncTimeRow = () => {
      const t = overlay.querySelector('#sch-time');
      t.disabled = !overlay.querySelector('#sch-en').checked;
    };
    overlay.querySelector('#sch-en').addEventListener('change', syncTimeRow);
    syncTimeRow();
    overlay.querySelector('#sch-cancel').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#sch-save').addEventListener('click', async () => {
      const en = overlay.querySelector('#sch-en').checked;
      const [h, m] = (overlay.querySelector('#sch-time').value || '06:30').split(':');
      try {
        await api('/api/settings', { method: 'POST', body: JSON.stringify({ schedule_enabled: en, hour: h, minute: m }) });
        overlay.remove();
        Toast.show(en ? `已开启：每天 ${h.padStart(2, '0')}:${m} 自动跑批` : '已切换为完全手动模式');
        this.refreshSys();
      } catch (_) { /* toast 已提示 */ }
    });
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
