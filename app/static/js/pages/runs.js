// 跑批历史页：运行列表 + 单次运行详情（节点结果 / 摄取留痕 / 日志）
window.Pages.runs = {
  async render(el, runId) {
    if (runId) return this.detail(el, runId);
    await this.list(el);
  },

  async list(el) {
    el.innerHTML = `
      <div class="card">
        <div class="row spread">
          <h3 style="margin:0">跑批历史 <span class="sub">摄取 → 转换 → 测试</span></h3>
          <button id="runs-refresh" class="btn btn-sm">↻ 刷新</button>
        </div>
        <div id="runs-list" class="mt8"></div>
      </div>`;
    document.getElementById('runs-refresh').addEventListener('click', () => this.list(el));

    const data = await api('/api/runs');
    const runs = data.runs || [];
    document.getElementById('runs-list').innerHTML = runs.length ? `
      <table class="tbl">
        <thead><tr><th>状态</th><th>运行编号</th><th>触发</th><th>开始</th><th>结束</th><th>耗时</th><th class="num">节点</th><th>明细</th></tr></thead>
        <tbody>${runs.map(r => `
          <tr>
            <td>${Light.html(r.status)}</td>
            <td style="font-family:Consolas,monospace;font-size:12px">${r.run_id}</td>
            <td>${r.trigger === 'schedule' ? '定时' : r.trigger === 'catchup' ? '补跑' : '手动'}</td>
            <td>${Fmt.dt(r.started_at)}</td>
            <td>${Fmt.dt(r.finished_at)}</td>
            <td>${Fmt.runDur(r)}</td>
            <td class="num">${r.counts ? (r.counts.total || '—') : '—'}</td>
            <td><a href="#/runs/${r.run_id}">查看 →</a></td>
          </tr>`).join('')}
        </tbody></table>`
      : '<div class="empty-tip">还没有跑批记录，点右上角"立即跑批"试试</div>';

    // 有跑批在进行时自动刷新
    try {
      const st = await api('/api/runs/status');
      if (st.active) App.poll(() => this.list(el), 4000);
    } catch (_) {}
  },

  async detail(el, runId) {
    let r;
    try { r = await api('/api/runs/' + runId); }
    catch (_) { el.innerHTML = '<div class="card empty-tip">运行记录不存在</div>'; return; }

    const ingestRows = ((r.ingest && r.ingest.results) || []).map(x => `
      <tr><td>${x.source}</td><td>${x.file || '—'}</td>
      <td class="num">${x.rows !== undefined ? Number(x.rows).toLocaleString('zh-CN') : '—'}</td>
      <td>${x.status === 'ok' ? '<span class="status-chip st-pass">成功</span>' : `<span class="status-chip st-fail">失败</span>`}</td></tr>`).join('');

    el.innerHTML = `
      <div class="row" style="padding-bottom:12px">
        <a href="#/runs">← 返回列表</a>
      </div>
      <div class="card">
        <div class="row spread">
          <div class="row">${Light.html(r.status)}
            <b style="font-family:Consolas,monospace">${r.run_id}</b>
            <span class="muted">${r.trigger === 'schedule' ? '定时触发' : r.trigger === 'catchup' ? '断档补跑' : '手动触发'}</span>
          </div>
          <span class="muted">${Fmt.dt(r.started_at)} → ${Fmt.dt(r.finished_at)} · 耗时 ${Fmt.runDur(r)}</span>
        </div>
        ${r.error ? `<div class="mt8" style="color:var(--red)">执行器异常：${r.error}</div>` : ''}
      </div>

      <div class="grid grid-2">
        <div class="card">
          <h3>数据摄取留痕 <span class="sub">谁进了库、进了多少行</span></h3>
          ${ingestRows ? `<table class="tbl"><thead><tr><th>数据源</th><th>文件</th><th class="num">行数</th><th>状态</th></tr></thead><tbody>${ingestRows}</tbody></table>`
            : '<div class="muted">无摄取记录（本轮未执行摄取）</div>'}
        </div>
        <div class="card">
          <h3>节点统计</h3>
          <div id="run-counts" class="row mt8"></div>
          <div class="muted mt16">红 = 失败并已拦截下游 · 黄 = 测试告警（数据质量提示） · 绿 = 全部通过</div>
        </div>
      </div>

      <div class="card">
        <h3>节点明细 <span class="sub">模型与测试</span></h3>
        <div style="max-height:460px;overflow:auto">
        <table class="tbl">
          <thead><tr><th style="width:70px">类型</th><th>名称</th><th style="width:90px">状态</th><th class="num" style="width:80px">耗时</th><th>信息</th></tr></thead>
          <tbody>
            ${(r.nodes || []).map(n => `
              <tr>
                <td><span class="kind ${n.kind === 'model' ? 'kind-model' : 'kind-log'}">${n.kind === 'model' ? '模型' : '测试'}</span></td>
                <td><b>${n.name}</b></td>
                <td>${StChip.html(n.status)}</td>
                <td class="num">${n.time !== undefined ? n.time + 's' : '—'}</td>
                <td class="muted" style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(n.message || '').replace(/"/g, '&quot;')}">${n.message || ''}</td>
              </tr>`).join('')}
          </tbody>
        </table></div>
      </div>

      <div class="card">
        <h3>运行日志 <span class="sub">末尾 400 行</span></h3>
        <div id="run-log" class="log-view">加载中…</div>
      </div>`;

    // 节点统计 chips
    const counts = r.counts || {};
    const order = ['success', 'pass', 'warn', 'error', 'fail', 'skipped', 'not_run'];
    document.getElementById('run-counts').innerHTML = order
      .filter(k => counts[k])
      .map(k => `<span class="pipe-chip"><span class="dot ${DOT_CLASS[k] || 'dot-gray'}"></span>${STATUS_LABEL[k] || k} × ${counts[k]}</span>`)
      .join('') || '<span class="muted">无</span>';

    // 日志
    try {
      const log = await fetch(`/api/runs/${runId}/log?tail=400`).then(x => x.text());
      const box = document.getElementById('run-log');
      box.textContent = log || '(空)';
      box.scrollTop = box.scrollHeight;
    } catch (_) {
      document.getElementById('run-log').textContent = '(日志加载失败)';
    }
  },
};
