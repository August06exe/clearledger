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

    let data;
    try {
      data = await api('/api/runs');
    } catch (e) {
      document.getElementById('runs-list').innerHTML = '<div class="empty-tip">加载失败（可能正在跑批），点"刷新"重试。</div>';
      return;
    }
    const runs = data.runs || [];
    document.getElementById('runs-list').innerHTML = runs.length ? `
      <table class="tbl">
        <thead><tr><th>状态</th><th>账套</th><th>运行编号</th><th>触发</th><th>开始</th><th>结束</th><th>耗时</th><th class="num">节点</th><th>明细</th></tr></thead>
        <tbody>${runs.map(r => `
          <tr>
            <td>${Light.html(r.status)}</td>
            <td>${r.instance || '—'}</td>
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
        <h3>⏱ 瀑布图 <span class="sub" id="run-gantt-sub">加载中…</span></h3>
        <div id="run-gantt" class="chart mt8"></div>
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
                <td><b>${App.alias(n.name)}</b></td>
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

    // 瀑布图（run_results 时间轴；旧运行无数据时降级为提示，不弹 toast）
    try {
      const resp = await fetch('/api/runs/' + runId + '/gantt');
      const g = await resp.json();
      if (!resp.ok) throw new Error((g && g.detail) || 'HTTP ' + resp.status);
      this.drawGantt(document.getElementById('run-gantt'), g);
    } catch (e) {
      const box = document.getElementById('run-gantt');
      if (box) box.innerHTML = '<div class="empty-tip">瀑布图不可用：' + String(e.message || e).replace(/</g, '&lt;') + '</div>';
      const sub = document.getElementById('run-gantt-sub');
      if (sub) sub.textContent = '—';
    }

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

  // ⏱ 瀑布图：ECharts custom series——y=节点（offset 升序、最早上方），x=秒，横条=起止区间
  drawGantt(box, g) {
    if (!box) return;
    const num = v => { const n = Number(v); return isNaN(n) ? 0 : n; };
    // 契约保证后端按 offset 升序返回；这里再排一次，确保 y 轴「最早上方」不依赖上游
    const nodes = (g.nodes || []).slice().sort((a, b) => num(a.offset_s) - num(b.offset_s));
    if (!nodes.length) { box.innerHTML = '<div class="empty-tip">无节点数据</div>'; return; }
    // y 轴自适应高度：每节点 ≥14px（留 20px 更易读），整图 ≥300px
    box.style.height = Math.max(300, nodes.length * 20 + 40) + 'px';
    const COLOR = {
      success: '#16A34A', pass: '#16A34A',
      warn: '#D97706',
      error: '#DC2626', fail: '#DC2626', 'runtime error': '#DC2626',
      skipped: '#94A3B8', not_run: '#CBD5E1',
    };
    const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    const sec = v => num(v).toFixed(3) + 's';
    App.chart(box, {
      tooltip: {
        confine: true,
        formatter: p => {
          const n = nodes[p.dataIndex] || {};
          return '<b>' + esc(App.alias(n.name)) + '</b>'
            + '<br/>状态：' + esc(STATUS_LABEL[n.status] || n.status || '—')
            + '<br/>耗时：' + esc(sec(n.duration_s)) + ' · 起始于第 ' + esc(sec(n.offset_s))
            + (n.message ? '<br/><span style="color:#64748B">' + esc(n.message) + '</span>' : '');
        },
      },
      grid: { left: 8, right: 24, top: 12, bottom: 0, containLabel: true },
      xAxis: { type: 'value', name: '秒', splitLine: { lineStyle: { color: '#EEF2F7' } } },
      yAxis: {
        type: 'category', inverse: true,   // 数据按 offset 升序 → inverse 让最早的排在最上方
        data: nodes.map(n => App.alias(n.name)),
        axisLabel: { fontSize: 11 },
        axisTick: { show: false },
      },
      series: [{
        type: 'custom',
        renderItem: (params, api) => {
          const start = api.coord([api.value(1), api.value(0)]);
          const end = api.coord([api.value(2), api.value(0)]);
          const h = Math.min(api.size([0, 1])[1] * 0.6, 14);
          return {
            type: 'rect',
            shape: {
              x: start[0], y: start[1] - h / 2,
              width: Math.max(end[0] - start[0], 2),   // 极短节点保底 2px 可见可悬停（tooltip 仍显真实耗时）
              height: h,
            },
            style: api.style(),
          };
        },
        encode: { x: [1, 2], y: 0 },
        itemStyle: { borderRadius: 3 },
        data: nodes.map((n, i) => ({
          name: n.name,
          value: [i, num(n.offset_s), num(n.offset_s) + num(n.duration_s)],
          itemStyle: { color: COLOR[String(n.status).toLowerCase()] || '#94A3B8' },
        })),
      }],
    });
    const sub = document.getElementById('run-gantt-sub');
    if (sub) sub.textContent = '总耗时 ' + Fmt.dur(g.total_s);
  },
};
