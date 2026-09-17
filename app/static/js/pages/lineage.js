// 数据血缘页：蜘蛛网依赖图（AntV G6）+ 节点详情 + 字段级血缘
window.Pages.lineage = {
  async render(el) {
    el.innerHTML = `
      <div class="row" style="padding-bottom:12px">
        <input id="flow-search" placeholder="搜索节点，回车定位…" class="btn" style="width:240px">
        <button id="flow-fit" class="btn btn-sm">适应画布</button>
        <span class="muted">拖拽平移 · 滚轮缩放 · 点击节点查看来龙去脉</span>
      </div>
      <div id="flow-wrap">
        <div id="flow-canvas-box">
          <div id="flow-canvas"></div>
          <div id="flow-legend">
            <span><span class="dot dot-green"></span>通过</span>
            <span><span class="dot dot-yellow"></span>告警</span>
            <span><span class="dot dot-red"></span>失败</span>
            <span><span class="dot dot-gray"></span>未跑/未知</span>
            <span class="muted">|</span>
            <span class="muted">虚线框 = 源数据</span>
          </div>
        </div>
        <div id="node-panel" class="card"><div class="empty">点击图中任意节点<br>查看它的来龙去脉</div></div>
      </div>`;

    const g = await api('/api/lineage/graph');
    const statusFill = {
      green: ['#ECFDF5', '#10B981'], yellow: ['#FFFBEB', '#F59E0B'],
      red: ['#FEF2F2', '#EF4444'], unknown: ['#F8FAFC', '#CBD5E1'],
    };
    const data = {
      nodes: g.nodes.map(n => {
        const [fill, stroke] = statusFill[n.status] || statusFill.unknown;
        return {
          id: n.uid,
          label: n.name,
          nodeType: n.resource_type,
          status: n.status,
          style: {
            fill, stroke,
            lineWidth: n.resource_type === 'source' ? 1.4 : 1.6,
            lineDash: n.resource_type === 'source' ? [4, 3] : null,
            radius: 8,
            shadowBlur: 4, shadowColor: 'rgba(15,30,60,.08)',
          },
          labelCfg: { style: { fontSize: 12.5, fill: '#1F2937' } },
        };
      }),
      edges: g.edges.map((e, i) => ({ id: 'e' + i, source: e.source, target: e.target })),
    };

    const box = document.getElementById('flow-canvas');
    const graph = new G6.Graph({
      container: box,
      width: box.clientWidth, height: box.clientHeight,
      layout: { type: 'dagre', rankdir: 'LR', nodesep: 16, ranksep: 72 },
      defaultNode: { type: 'rect', size: [158, 38] },
      defaultEdge: {
        type: 'polyline',
        style: { stroke: '#B9C3D6', lineWidth: 1.2, radius: 10,
          endArrow: { path: G6.Arrow.triangle(7, 7, 0), fill: '#B9C3D6' } },
      },
      modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
      animate: false,
    });
    graph.data(data);
    graph.render();
    graph.fitView(20);
    App.graph = graph;

    // ---- tooltip ----
    const tip = document.createElement('div');
    tip.className = 'g6-tooltip';
    tip.style.display = 'none';
    document.getElementById('flow-canvas-box').appendChild(tip);
    const byUid = Object.fromEntries(g.nodes.map(n => [n.uid, n]));
    graph.on('node:mouseenter', evt => {
      const n = byUid[evt.item.getID()];
      if (!n) return;
      tip.innerHTML = `<b>${n.name}</b><br>${n.schema || ''} · ${n.resource_type === 'source' ? '源数据' : '模型'}
        ${n.description ? '<br>' + n.description.slice(0, 80) : ''}`;
      tip.style.display = 'block';
    });
    graph.on('node:mousemove', evt => {
      const rect = box.getBoundingClientRect();
      tip.style.left = Math.min(evt.canvasX + 14, rect.width - 260) + 'px';
      tip.style.top = (evt.canvasY + 14) + 'px';
    });
    graph.on('node:mouseleave', () => { tip.style.display = 'none'; });

    graph.on('node:click', evt => this.showPanel(byUid[evt.item.getID()]));

    document.getElementById('flow-fit').onclick = () => graph.fitView(20);
    document.getElementById('flow-search').addEventListener('keydown', e => {
      if (e.key !== 'Enter') return;
      const q = e.target.value.trim().toLowerCase();
      if (!q) return;
      const hit = g.nodes.find(n => n.name.toLowerCase().includes(q));
      if (!hit) { Toast.show('没有匹配的节点', true); return; }
      const item = graph.findById(hit.uid);
      if (item) { graph.focusItem(item, true, { easing: 'easeCubic', duration: 300 }); this.showPanel(hit); }
    });
  },

  async showPanel(n) {
    const panel = document.getElementById('node-panel');
    if (!n) return;
    panel.innerHTML = '<div class="empty">加载中…</div>';
    let detail = null;
    try { detail = await api('/api/node/' + encodeURIComponent(n.uid)); } catch (_) {}
    const d = detail || {};
    const stTime = d.last_time !== undefined ? ` · ${d.last_time}s` : '';

    panel.innerHTML = `
      <div class="row spread">
        <h3 style="margin:0">${n.name}</h3>
        ${StChip.html(n.status)}
      </div>
      <div class="muted mt8">${n.schema || ''} · ${n.resource_type === 'source' ? '源数据' : '数据模型'}${stTime}</div>
      ${d.description ? `<p class="mt8" style="line-height:1.7">${d.description}</p>` : ''}
      ${d.last_message && ['error', 'fail', 'runtime error', 'warn'].includes(n.status)
        ? `<div class="mt8" style="background:var(--red-bg);color:var(--red);border-radius:8px;padding:8px 10px;font-size:12px;white-space:pre-wrap">${(d.last_message || '').slice(0, 400)}</div>` : ''}
      ${n.tags && n.tags.length ? `<div class="mt8">${n.tags.map(t => `<span class="kind kind-model">${t}</span>`).join(' ')}</div>` : ''}

      <h3 class="mt16">质量测试 <span class="sub">${(d.tests || []).length} 项</span></h3>
      ${(d.tests || []).length ? `<table class="tbl"><tbody>${d.tests.map(t => `
        <tr><td style="width:70px"><span class="muted">${t.kind}</span></td>
        <td>${t.name}${t.severity === 'warn' ? ' <span class="status-chip st-warn">warn</span>' : ''}</td></tr>`).join('')}
      </tbody></table>` : '<div class="muted">无</div>'}

      <h3 class="mt16">字段与口径 <span class="sub">${(d.columns || []).length} 个字段</span></h3>
      <div style="max-height:230px;overflow:auto">
      <table class="tbl"><thead><tr><th>字段</th><th>类型</th><th>业务含义</th></tr></thead><tbody>
        ${(d.columns || []).map(c => `<tr><td style="white-space:nowrap"><b>${c.name}</b></td>
          <td class="muted" style="white-space:nowrap">${c.type || '—'}</td>
          <td>${c.description || ''}</td></tr>`).join('')}
      </tbody></table></div>

      <div id="col-lineage" class="mt16"><div class="muted">字段级血缘解析中…</div></div>`;

    if (n.resource_type !== 'model') {
      const cl = document.getElementById('col-lineage');
      if (cl) cl.innerHTML = '<div class="muted">源数据节点无字段级血缘（它是血缘的起点）。</div>';
      return;
    }
    try {
      const colLin = await api('/api/lineage/columns/' + encodeURIComponent(n.name));
      const boxEl = document.getElementById('col-lineage');
      if (!boxEl) return;
      if (!colLin.available) {
        boxEl.innerHTML = `<h3>字段级血缘</h3><div class="muted">${colLin.reason || '暂不可用'}</div>`;
        return;
      }
      const rows = colLin.columns.map(c => `
        <tr><td style="white-space:nowrap"><b>${c.column}</b></td>
        <td>${c.upstreams.length
          ? c.upstreams.map(u => `${u.table}.<b>${u.column}</b>`).join('<br>')
          : (c.ok ? '<span class="muted">计算字段（无直接上游列）</span>' : '<span class="muted">解析失败</span>')}</td></tr>`).join('');
      boxEl.innerHTML = `
        <h3>字段级血缘 <span class="sub">输出字段 ← 上游来源</span></h3>
        <div style="max-height:240px;overflow:auto">
        <table class="tbl"><thead><tr><th>本层字段</th><th>来自上游</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    } catch (_) {
      const boxEl = document.getElementById('col-lineage');
      if (boxEl) boxEl.innerHTML = '<h3>字段级血缘</h3><div class="muted">解析暂不可用</div>';
    }
  },
};
