// 总览页：账套感知——红绿灯 / 动态 KPI 卡 / 走势 / 最近跑批
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
    const timeKey = Object.keys(k)[0] || null;
    const metricNames = Object.keys(k).filter(x => x !== timeKey);
    const schedTxt = ov.schedule && ov.schedule.schedule_enabled
      ? `每天 ${String(ov.schedule.schedule_hour).padStart(2, '0')}:${String(ov.schedule.schedule_minute).padStart(2, '0')} 自动跑批`
      : '跑批模式：手动';
    const instTitle = ov.instance ? ov.instance.title : '';

    const warnsHtml = (ov.warnings || []).length
      ? `<div class="mt8">${ov.warnings.slice(0, 3).map(w =>
          `<div class="row" style="margin-bottom:6px"><span class="dot dot-yellow"></span>
           <b>${w.name}</b><span class="muted">${(w.message || '').slice(0, 140)}</span></div>`).join('')}
        <div class="muted mt8">黄灯 = 跑批成功但数据质量告警，报表已按当前口径发布，请关注上游数据。</div></div>`
      : '';

    const kpiCards = metricNames.slice(0, 4).map((m, i) =>
      this.kpiCard(m, k[m], p[m], [' #3B82F6', '#10B981', '#8B5CF6', '#F59E0B'][i], timeKey)).join('');
    const extraCount = Math.max(0, metricNames.length - 4);

    el.innerHTML = `
      <div class="card">
        <div class="row spread">
          <div class="row">
            ${Light.html(running ? 'running' : ov.light)}
            <div>
              <div style="font-weight:700">
                ${running ? '跑批进行中…' : (lr ? `上次跑批 ${Fmt.dt(lr.finished_at)}（${lr.trigger === 'schedule' ? '定时' : lr.trigger === 'catchup' ? '补跑' : '手动'}）` : '尚未跑批')}
              </div>
              <div class="muted">
                ${instTitle} · ${schedTxt} · 节点 ${lr && lr.counts ? (lr.counts.total || '—') : '—'} 个
              </div>
            </div>
          </div>
          <div class="muted">${ov.app.name} · 账套【${instTitle}】</div>
        </div>
        ${warnsHtml}
      </div>

      <div class="grid grid-4">${kpiCards}</div>
      ${extraCount > 0 ? `<div class="muted mt8">另有 ${extraCount} 项指标可在"管理报表"中查看</div>` : ''}

      <div class="grid grid-2 mt16">
        <div class="card"><h3>指标走势 <span class="sub">按${timeKey || '期'}</span></h3><div id="ov-trend" class="chart"></div></div>
        <div class="card"><h3>比率走势</h3><div id="ov-margin" class="chart"></div></div>
      </div>

      <div class="grid grid-2 mt16">
        <div class="card">
          <h3>管道节点状态 <span class="sub">血缘图实时数据</span></h3>
          <div id="ov-pipe"></div>
          <div class="muted mt8">红/黄/绿来自最近一次跑批；点击左侧"数据血缘"查看依赖图。</div>
        </div>
        <div class="card">
          <h3>最近跑批</h3>
          <table class="tbl"><thead><tr><th>状态</th><th>账套</th><th>时间</th><th>触发</th><th class="num">节点</th></tr></thead>
          <tbody>${(runs.runs || []).slice(0, 5).map(r => `
            <tr style="cursor:pointer" onclick="location.hash='#/runs/${r.run_id}'">
              <td>${Light.html(r.status)}</td>
              <td>${r.instance || '—'}</td>
              <td>${Fmt.dt(r.finished_at)}</td>
              <td>${r.trigger === 'schedule' ? '定时' : r.trigger === 'catchup' ? '补跑' : '手动'}</td>
              <td class="num">${r.counts ? (r.counts.total || '—') : '—'}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="muted">暂无记录</td></tr>'}
          </tbody></table>
        </div>
      </div>`;

    this.drawTrend(ov.trend || [], timeKey, metricNames);

    // ---- 管道 chips：按 schema 分组（来自血缘图真实节点）----
    const groups = {};
    graph.nodes.forEach(n => { (groups[n.schema || 'other'] = groups[n.schema || 'other'] || []).push(n); });
    const order = { raw: '① 源数据', staging: '② 清洗层', intermediate: '③ 加工层', marts: '④ 报表层' };
    document.getElementById('ov-pipe').innerHTML = Object.keys(order).map(sch => {
      const items = groups[sch] || [];
      if (!items.length) return '';
      return `<div style="margin-bottom:6px">
        <div class="muted" style="margin:6px 0 2px">${order[sch]}</div>
        ${items.map(n => `<span class="pipe-chip" title="${n.name}"><span class="dot ${DOT_CLASS[n.status] || 'dot-gray'}"></span>${App.alias(n.name)}</span>`).join('')}
      </div>`;
    }).join('') || '<div class="muted">暂无管道数据</div>';
  },

  isRate(name) { return name.includes('率') || name.includes('比'); },

  fmtMetric(name, v) {
    if (v === null || v === undefined) return '—';
    return this.isRate(name) ? Fmt.pct(v) : Fmt.wan(v);
  },

  kpiCard(title, cur, prev, accent) {
    let delta = '—', cls = 'flat';
    if (cur !== null && prev !== null && prev !== 0) {
      if (this.isRate(title)) {
        const d = cur - prev;
        delta = `${d >= 0 ? '↑' : '↓'} ${Math.abs(d * 100).toFixed(1)} pct`;
        cls = d >= 0 ? 'up' : 'down';
      } else {
        const d = cur / prev - 1;
        delta = `${d >= 0 ? '↑' : '↓'} ${Math.abs(d * 100).toFixed(1)}%`;
        cls = d >= 0 ? 'up' : 'down';
      }
    }
    return `
      <div class="card kpi-card" style="margin-bottom:0">
        <div class="kpi-accent" style="background:linear-gradient(90deg, ${accent}, ${accent}44)"></div>
        <div class="muted">${title}</div>
        <div class="kpi-value">${this.fmtMetric(title, cur)}</div>
        <div class="kpi-delta ${cls}">${delta} <span class="muted" style="font-weight:400">较上期</span></div>
      </div>`;
  },

  drawTrend(trend, timeKey, metricNames) {
    if (!trend.length || !timeKey) return;
    const rows = trend.slice().sort((a, b) => String(a[timeKey]).localeCompare(String(b[timeKey])));
    const labels = rows.map(r => String(r[timeKey]).slice(0, 7));
    const wan = v => v === null || v === undefined ? null : +(v / 1e4).toFixed(1);
    const rates = metricNames.filter(this.isRate);
    const volumes = metricNames.filter(m => !this.isRate(m));

    App.chart(document.getElementById('ov-trend'), {
      tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
      legend: { top: 0, data: volumes.slice(0, 3) },
      grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value', axisLabel: { formatter: v => v + ' 万' } },
      series: volumes.slice(0, 3).map((m, i) => ({
        name: m, type: i === 0 ? 'bar' : 'line', smooth: i > 0, barMaxWidth: 24,
        itemStyle: { color: ['#3B82F6', '#10B981', '#8B5CF6'][i] },
        lineStyle: { width: 2.5, color: ['#3B82F6', '#10B981', '#8B5CF6'][i] },
        data: rows.map(r => wan(r[m])),
      })),
    });

    App.chart(document.getElementById('ov-margin'), {
      tooltip: { trigger: 'axis', valueFormatter: v => v + '%' },
      legend: { top: 0, data: rates.slice(0, 3) },
      grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
      xAxis: { type: 'category', data: labels },
      yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
      series: rates.slice(0, 3).map((m, i) => ({
        name: m, type: 'line', smooth: true,
        itemStyle: { color: ['#1D4ED8', '#D97706', '#0D9488'][i] },
        data: rows.map(r => r[m] === null || r[m] === undefined ? null : +(r[m] * 100).toFixed(1)),
      })),
    });
  },
};
