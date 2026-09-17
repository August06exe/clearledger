// 总览页：系统红绿灯 / KPI 卡 / 走势 / 管道状态 / 最近跑批
window.Pages.overview = {
  async render(el) {
    let ov, runs, graph;
    try {
      [ov, runs, graph] = await Promise.all([
        api('/api/overview'), api('/api/runs'), api('/api/lineage/graph'),
      ]);
    } catch (e) {
      el.innerHTML = '<div class="card empty-tip">数据仓库未就绪。<br>请点击右上角"立即跑批"，或先运行一次数据管道。</div>';
      return;
    }

    const running = ov.running && ov.running.active;
    const lr = ov.last_run;
    const k = ov.kpi.latest || {};
    const p = ov.kpi.prev || {};
    const delta = (a, b) => (a && b ? a / b - 1 : null);
    const revD = delta(k.revenue, p.revenue);
    const gpD = delta(k.gross_profit, p.gross_profit);
    const npD = delta(k.net_profit, p.net_profit);
    const mgD = (k.gross_margin !== undefined && p.gross_margin !== undefined && k.gross_margin !== null)
      ? k.gross_margin - p.gross_margin : null;
    const monthLabel = k.month ? String(k.month).slice(0, 7) : '—';

    const warnsHtml = (ov.warnings || []).length
      ? `<div class="mt8">${ov.warnings.map(w =>
          `<div class="row" style="margin-bottom:6px"><span class="dot dot-yellow"></span>
           <b>${w.name}</b><span class="muted">${(w.message || '').slice(0, 160)}</span></div>`).join('')}
        <div class="muted mt8">黄灯 = 跑批成功但数据质量告警，报表已按当前口径发布，请关注上游数据。</div></div>`
      : '';

    el.innerHTML = `
      <div class="card">
        <div class="row spread">
          <div class="row">
            ${Light.html(running ? 'running' : ov.light)}
            <div>
              <div style="font-weight:700">
                ${running ? '跑批进行中…' : (lr ? `上次跑批 ${Fmt.dt(lr.finished_at)}（${lr.trigger === 'schedule' ? '定时' : '手动'}）` : '尚未跑批')}
              </div>
              <div class="muted">
                ${lr ? `节点 ${lr.counts.total || '—'} 个 · 计划任务 ${ov.schedule.label}` : `计划任务 ${ov.schedule.label} · 首次使用请先点右上角"立即跑批"`}
              </div>
            </div>
          </div>
          <div class="muted">${ov.app.name} · ${ov.node_counts.model || 0} 个模型 · ${ov.node_counts.source || 0} 个数据源</div>
        </div>
        ${warnsHtml}
      </div>

      <div class="grid grid-4">
        ${this.kpiCard('营业收入', Fmt.wan(k.revenue), Fmt.signedPct(revD), revD, `${monthLabel} 完整月`)}
        ${this.kpiCard('毛利', Fmt.wan(k.gross_profit), Fmt.signedPct(gpD), gpD, `毛利率 ${Fmt.pct(k.gross_margin)}`)}
        ${this.kpiCard('净利', Fmt.wan(k.net_profit), Fmt.signedPct(npD), npD, `净利率 ${Fmt.pct(k.net_margin)}`)}
        ${this.kpiCard('毛利率', Fmt.pct(k.gross_margin),
          mgD === null ? '—' : `${mgD >= 0 ? '↑' : '↓'} ${Math.abs(mgD * 100).toFixed(1)} pct`, mgD, '毛利 / 收入')}
      </div>

      <div class="grid grid-2">
        <div class="card"><h3>收入与净利走势 <span class="sub">近 13 个完整月 · 万元</span></h3><div id="ov-trend" class="chart"></div></div>
        <div class="card"><h3>利润率走势</h3><div id="ov-margin" class="chart"></div></div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <h3>管道节点状态 <span class="sub">按数据分层</span></h3>
          <div id="ov-pipe"></div>
          <div class="muted mt8">红/黄/绿来自最近一次跑批；点击左侧"数据血缘"查看依赖图。</div>
        </div>
        <div class="card">
          <h3>最近跑批</h3>
          <table class="tbl"><thead><tr><th>状态</th><th>时间</th><th>触发</th><th class="num">节点</th><th>耗时</th></tr></thead>
          <tbody>${(runs.runs || []).slice(0, 5).map(r => `
            <tr style="cursor:pointer" onclick="location.hash='#/runs/${r.run_id}'">
              <td>${Light.html(r.status)}</td>
              <td>${Fmt.dt(r.finished_at)}</td>
              <td>${r.trigger === 'schedule' ? '定时' : '手动'}</td>
              <td class="num">${r.counts ? (r.counts.total || '—') : '—'}</td>
              <td>${Fmt.runDur(r)}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="muted">暂无记录</td></tr>'}
          </tbody></table>
        </div>
      </div>`;

    // ---- 图表 ----
    const trend = (ov.trend || []).slice();
    const months = trend.map(r => String(r.month).slice(0, 7));
    App.chart(document.getElementById('ov-trend'), {
      tooltip: { trigger: 'axis' },
      legend: { data: ['收入', '净利'], top: 0 },
      grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
      xAxis: { type: 'category', data: months },
      yAxis: { type: 'value', axisLabel: { formatter: v => v + ' 万' } },
      series: [
        { name: '收入', type: 'bar', data: trend.map(r => r.revenue === null ? null : +(r.revenue / 1e4).toFixed(1)),
          itemStyle: { color: '#3B82F6', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
        { name: '净利', type: 'line', smooth: true, data: trend.map(r => r.net_profit === null ? null : +(r.net_profit / 1e4).toFixed(1)),
          itemStyle: { color: '#16A34A' }, lineStyle: { width: 2.5 } },
      ],
    });
    App.chart(document.getElementById('ov-margin'), {
      tooltip: { trigger: 'axis', valueFormatter: v => v + '%' },
      legend: { data: ['毛利率', '净利率'], top: 0 },
      grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
      xAxis: { type: 'category', data: months },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: [
        { name: '毛利率', type: 'line', smooth: true, data: trend.map(r => r.gross_margin === null ? null : +(r.gross_margin * 100).toFixed(1)), itemStyle: { color: '#1D4ED8' } },
        { name: '净利率', type: 'line', smooth: true, data: trend.map(r => r.net_margin === null ? null : +(r.net_margin * 100).toFixed(1)), itemStyle: { color: '#D97706' } },
      ],
    });

    // ---- 管道 chips ----
    const statusByUid = {};
    (graph.nodes || []).forEach(n => statusByUid[n.uid] = n.status);
    const groups = { raw: '① 源数据 raw', staging: '② 清洗层 staging', intermediate: '③ 加工层 intermediate', marts: '④ 报表层 marts' };
    const bySchema = {};
    graph.nodes.forEach(n => { (bySchema[n.schema] = bySchema[n.schema] || []).push(n); });
    document.getElementById('ov-pipe').innerHTML = Object.entries(groups).map(([sch, label]) => `
      <div style="margin-bottom:6px">
        <div class="muted" style="margin:6px 0 2px">${label}</div>
        ${(bySchema[sch] || []).map(n => `
          <span class="pipe-chip"><span class="dot ${DOT_CLASS[n.status] || 'dot-gray'}"></span>${n.name}</span>`).join('')}
      </div>`).join('');
  },

  kpiCard(title, value, delta, deltaVal, sub) {
    const cls = deltaVal === null || deltaVal === undefined ? 'flat' : (deltaVal >= 0 ? 'up' : 'down');
    return `
      <div class="card" style="margin-bottom:0">
        <div class="muted">${title}</div>
        <div class="kpi-value">${value}</div>
        <div class="kpi-delta ${cls}">${delta || ''} <span class="muted" style="font-weight:400">${sub || ''}</span></div>
      </div>`;
  },
};
