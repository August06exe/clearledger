// 数据字典页：全库表与字段的业务含义（AI 撰写、随管道自动更新）
window.Pages.dictionary = {
  async render(el) {
    el.innerHTML = `
      <div id="dict-wrap">
        <div id="dict-list" class="card">
          <h3>数据字典 <span class="sub">表 · 字段 · 口径</span></h3>
          <input id="dict-search" placeholder="搜索表名 / 字段 / 含义…" class="btn" style="width:100%">
          <div id="dict-tables"></div>
        </div>
        <div id="dict-detail" class="card"><div class="empty">左侧选择一张表<br>查看它的字段与业务含义</div></div>
      </div>`;

    const data = await api('/api/dictionary');
    this.tables = data.tables;
    this.renderList('');

    document.getElementById('dict-search').addEventListener('input', e =>
      this.renderList(e.target.value.trim().toLowerCase()));
  },

  renderList(q) {
    const box = document.getElementById('dict-tables');
    const order = { raw: '① raw 源数据', staging: '② staging 清洗', intermediate: '③ intermediate 加工', marts: '④ marts 报表' };
    const match = t => {
      if (!q) return true;
      if ((t.name || '').toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q)) return true;
      return (t.columns || []).some(c =>
        (c.name || '').toLowerCase().includes(q) || (c.description || '').toLowerCase().includes(q));
    };
    const groups = {};
    this.tables.filter(match).forEach(t => (groups[t.schema] = groups[t.schema] || []).push(t));

    box.innerHTML = Object.entries(order).map(([sch, label]) => {
      const items = groups[sch] || [];
      if (!items.length) return '';
      return `<div class="muted" style="margin:10px 0 4px">${label}</div>` + items.map(t => `
        <div class="dict-item" data-uid="${t.uid}">
          <span class="kind kind-${t.kind === 'source' ? 'source' : t.kind === 'log' ? 'log' : 'model'}">${t.kind === 'source' ? '源' : t.kind === 'log' ? '日志' : '模型'}</span>
          <span>${t.name}</span>
        </div>`).join('');
    }).join('') || '<div class="empty-tip">没有匹配的表</div>';

    box.querySelectorAll('.dict-item').forEach(item =>
      item.addEventListener('click', () => {
        box.querySelectorAll('.dict-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        this.showDetail(item.dataset.uid);
      }));
  },

  showDetail(uid) {
    const t = this.tables.find(x => x.uid === uid);
    if (!t) return;
    document.getElementById('dict-detail').innerHTML = `
      <div class="row spread">
        <h3 style="margin:0">${t.name} <span class="kind kind-${t.kind === 'source' ? 'source' : t.kind === 'log' ? 'log' : 'model'}">${t.schema}</span></h3>
        <span class="muted">${(t.columns || []).length} 个字段 · ${t.test_count} 项质量测试</span>
      </div>
      ${t.description ? `<p class="mt8 muted" style="line-height:1.7">${t.description}</p>` : ''}
      <table class="tbl mt16">
        <thead><tr><th style="width:220px">字段名</th><th style="width:140px">类型</th><th>业务含义</th></tr></thead>
        <tbody>
          ${(t.columns || []).map(c => `
            <tr><td><b>${c.name}</b></td><td class="muted">${c.type || '—'}</td><td>${c.description || ''}</td></tr>`).join('')}
        </tbody>
      </table>`;
  },
};
