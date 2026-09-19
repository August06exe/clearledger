// 管理报表页：账套感知——报表列表来自 dashboard.yml，列=维度+指标，图表类型配置驱动
window.Pages.reports = {
  async render(el, key) {
    let data;
    try {
      data = await api('/api/reports');
    } catch (e) {
      el.innerHTML = '<div class="card empty-tip">报表配置加载失败（可能正在跑批或仓库未就绪）。<br>稍等片刻后点击左侧导航重试。</div>';
      return;
    }
    this.options = data.options || {};
    const reports = data.reports || [];
    if (!reports.length) {
      el.innerHTML = '<div class="card empty-tip">当前账套没有配置报表。</div>';
      return;
    }
    if (!key || !reports.find(r => r.key === key)) key = reports[0].key;
    this.key = key;

    el.innerHTML = `
      <div id="report-wrap">
        <div id="report-list">
          ${reports.map(r => `
            <div class="report-item ${r.key === key ? 'active' : ''}" data-key="${r.key}">
              <div class="t">${r.title}</div>
              <div class="d">${(r.metrics || []).join(' / ')}</div>
            </div>`).join('')}
          <div class="report-item" style="cursor:default;border:1px dashed var(--border)">
            <div class="t muted" style="font-weight:600">⚙ 本页报表不是写死的</div>
            <div class="d">每张报表 = instances/账套/dashboard.yml 里的一行配置
              （维度 × 指标 × 筛选）。想增删报表、改指标口径，直接对 AI 助手说，
              或改配置后重新跑批。可视化编辑器在 v0.5 配置工作台。</div>
          </div>
        </div>
        <div id="report-main" class="card"></div>
      </div>`;

    document.querySelectorAll('.report-item').forEach(item =>
      item.addEventListener('click', () => {
        if (item.dataset.key === this.key) return;
        location.hash = '#/reports/' + item.dataset.key;
      }));

    this.renderReport();
  },

  async renderReport() {
    const main = document.getElementById('report-main');
    let meta;
    try {
      meta = (await api('/api/reports')).reports.find(r => r.key === this.key);
    } catch (e) {
      main.innerHTML = '<div class="empty-tip">加载失败，稍后重试</div>';
      return;
    }
    if (!meta) { main.innerHTML = '<div class="empty-tip">报表不存在</div>'; return; }
    this.meta = meta;

    // 参数栏：全部 select（维度筛选，选项来自语义层白名单）
    const paramsHtml = (meta.params || []).map(p => {
      const opts = this.options[p.options_from] || [];
      return `<div><label>${p.label}</label>
        <select data-param="${p.name}">
          <option value="">全部</option>
          ${opts.map(o => `<option value="${o}">${o}</option>`).join('')}
        </select></div>`;
    }).join('');

    main.innerHTML = `
      <div id="rp-stale" style="display:none;background:var(--red-bg);color:var(--red);
        border-radius:8px;padding:9px 12px;font-size:13px;font-weight:600;margin-bottom:14px"></div>
      <div class="row spread">
        <h3 style="margin:0">${meta.title}</h3>
        <div class="row">
          <button id="rp-caliber" class="btn btn-sm">📐 口径</button>
          <button id="rp-query" class="btn btn-primary btn-sm">查询</button>
          <button id="rp-export" class="btn btn-sm">⬇ 导出 Excel</button>
        </div>
      </div>
      <div class="muted mt8">指标：${(meta.metrics || []).join('、')}　维度：${meta.dimension}${meta.time_dim ? ' × ' + meta.time_dim : ''}</div>
      <div class="param-bar mt16">${paramsHtml || '<span class="muted">无筛选参数</span>'}</div>
      <div id="rp-chart" class="chart"></div>
      <div id="rp-table" class="mt16" style="max-height:420px;overflow:auto"></div>`;

    document.getElementById('rp-query').addEventListener('click', () => this.query());
    document.getElementById('rp-export').addEventListener('click', () => {
      window.open('/api/reports/' + this.key + '/export?' + this.qs(), '_blank');
    });
    document.getElementById('rp-caliber').addEventListener('click', () => this.showCaliber(meta));
    this.query();
  },

  async showCaliber(meta) {
    let cal;
    try {
      cal = await api('/api/caliber');
    } catch (e) { return; }
    const metricNames = meta.metrics || [];
    const metricMap = Object.fromEntries(cal.metrics.map(m => [m.name, m]));
    const rows = metricNames.map(n => {
      const m = metricMap[n] || { name: n, expr: '（未在 metrics.yml 中找到）', desc: '' };
      return `<tr>
        <td style="white-space:nowrap"><b>${m.name}</b></td>
        <td style="font-family:Consolas,monospace;font-size:12px;color:#1D4ED8">${(m.expr || '').replace(/</g, '&lt;')}</td>
        <td>${m.desc || '—'}</td>
      </tr>`;
    }).join('');
    const usedDims = [meta.dimension, meta.time_dim, ...(this.meta && [])]
      .filter(Boolean).map(d => d).join(' × ');
    const overlay = App.el(`
      <div id="modal-overlay">
        <div class="modal card" style="width:640px;max-height:80vh;overflow:auto">
          <div class="row spread">
            <h3 style="margin:0">📐 ${meta.title} · 指标口径</h3>
            <button class="btn btn-sm" id="cal-close">✕</button>
          </div>
          <div class="muted mt8" style="line-height:1.7">
            账套【${cal.instance.title}】 · 分组维度：${usedDims || '—'}<br>
            口径唯一出处：<code>instances/${cal.instance.name}/metrics.yml</code>（本页只读展示，改口径=改配置后重跑）
          </div>
          <table class="tbl mt16">
            <thead><tr><th>指标</th><th>计算公式</th><th>业务说明</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
          <div class="muted mt8" style="line-height:1.6">
            派生列口径（宽表层，公式中的字段来源）：
            ${cal.derived.filter(d => metricNames.length === 0 || true).slice(0, 12).map(d =>
              `<span class="pipe-chip" title="${(d.desc || '').replace(/"/g, '&quot;')}">${d.name}</span>`).join('')}
            <span class="muted">（悬停查看说明；完整定义见数据字典页）</span>
          </div>
        </div>
      </div>`);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#cal-close').addEventListener('click', () => overlay.remove());
  },

  qs() {
    const params = [];
    document.querySelectorAll('#report-main [data-param]').forEach(inp => {
      const v = inp.value;
      if (v !== '' && v !== null && v !== undefined) params.push(`${inp.dataset.param}=${encodeURIComponent(v)}`);
    });
    return params.join('&');
  },

  async query() {
    const table = document.getElementById('rp-table');
    if (!table) return;
    try {
      const r = await api(`/api/reports/${this.key}/data?` + this.qs());
      this.last = r;
      const banner = document.getElementById('rp-stale');
      if (banner) {
        if (r.stale) {
          banner.textContent = '⚠ ' + (r.stale_info || '数据过期：最近跑批失败，以下为上次成功数据');
          banner.style.display = '';
        } else banner.style.display = 'none';
      }
      const cols = r.columns || [];
      if (!r.rows.length) {
        table.innerHTML = '<div class="empty-tip">没有数据</div>';
      } else {
        table.innerHTML = `
          <table class="tbl"><thead><tr>
            ${cols.map(([, label]) => `<th class="${this.isNum(label) ? 'num' : ''}">${label}</th>`).join('')}
          </tr></thead>
          <tbody>${r.rows.map(row => `<tr>
            ${cols.map(([key, label], i) => `<td class="${this.isNum(label) ? 'num' : ''}">${this.fmtCell(label, row[key], i)}</td>`).join('')}
          </tr>`).join('')}</tbody></table>`;
      }
      this.drawChart(cols, r.rows);
    } catch (e) {
      table.innerHTML = '<div class="empty-tip">查询失败（可能正在跑批，稍后再试）</div>';
    }
  },

  isNum(label) {
    return !this.isTextDim(label) && !label.includes('率') && !label.includes('比');
  },

  isTextDim(label) {
    return ['月份', '区域', '行业', '客户等级', '状态', '门店', '城市', '商圈类型', '菜品类别',
      '渠道', '品类', '商品名称', '商品编号', '客户名称', '客户编号', '部门名称', '部门编码',
      '费用类别', '最近下单', '大区', '供应商', '事业部', '交付组', '合同', '客户',
      '事项类型', '岗位'].includes(label);
  },

  isRate(label) {
    return typeof label === 'string' && (label.includes('率') || label.includes('比') || label.includes('占比'));
  },

  fmtCell(label, v, idx) {
    if (v === null || v === undefined) return '—';
    if (this.isRate(label)) return Fmt.pct(v);
    if (!this.isNum(label) || idx === 0) {
      return /日期|时间|月份|月/.test(label) ? String(v).slice(0, 10) : String(v);
    }
    return Fmt.yuan(v);
  },

  drawChart(cols, rows) {
    const el = document.getElementById('rp-chart');
    if (!el) return;
    const meta = this.meta || {};
    if (!rows.length) { el.style.display = 'none'; return; }
    el.style.display = '';
    const keys = cols.map(c => c[0]);
    const dimKey = meta.dimension;
    const timeKey = meta.time_dim;
    const rateKeys = keys.filter(k => this.isRate(k));
    const volKeys = keys.filter(k => !this.isRate(k) && k !== dimKey && k !== timeKey);
    const wan = v => v === null || v === undefined ? null : +(v / 1e4).toFixed(1);
    const sortAsc = r => {
      const s = rows.slice().sort((a, b) => String(a[timeKey || dimKey]).localeCompare(String(b[timeKey || dimKey])));
      return timeKey ? s : s.reverse();
    };

    if (!timeKey) {
      // 无时间维度：横向条形排行（Top 15）
      const top = rows.slice(0, 15).slice().reverse();
      App.chart(el, {
        tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
        grid: { left: 8, right: 30, top: 10, bottom: 0, containLabel: true },
        xAxis: { type: 'value', name: '万元' },
        yAxis: { type: 'category', data: top.map(r => r[dimKey]), axisLabel: { fontSize: 11 } },
        series: volKeys.slice(0, 1).map((k, i) => ({
          name: k, type: 'bar', barMaxWidth: 14,
          itemStyle: { color: '#1D4ED8', borderRadius: [0, 4, 4, 0] },
          data: top.map(r => wan(r[k])),
        })),
      });
      return;
    }

    const asc = sortAsc();
    const months = [...new Set(asc.map(r => String(r[timeKey]).slice(0, 7)))];

    if (dimKey === timeKey || asc.every(r => r[dimKey] === r[timeKey]) || asc.length === months.length && !asc.some(r => r[dimKey] !== r[timeKey] && !months.includes(String(r[dimKey]).slice(0, 7)))) {
      // 维度即时间（公司级月报）：指标系列
      const series = [];
      volKeys.slice(0, 2).forEach((k, i) => series.push({
        name: k, type: i === 0 ? 'bar' : 'line', smooth: i > 0, barMaxWidth: 26,
        itemStyle: { color: ['#3B82F6', '#16A34A'][i] },
        data: asc.map(r => wan(r[k])),
      }));
      rateKeys.slice(0, 1).forEach(k => series.push({
        name: k, type: 'line', yAxisIndex: 1, smooth: true, itemStyle: { color: '#D97706' },
        data: asc.map(r => r[k] === null ? null : +(r[k] * 100).toFixed(1)),
      }));
      App.chart(el, {
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        grid: { left: 8, right: 44, top: 34, bottom: 0, containLabel: true },
        xAxis: { type: 'category', data: months },
        yAxis: [{ type: 'value', name: '万元' }, { type: 'value', name: '%', position: 'right', axisLabel: { formatter: '{value}%' } }],
        series,
      });
      return;
    }

    // 时间 × 维度：按维度值堆叠（第一个量值指标）
    const dims = [...new Set(asc.map(r => r[dimKey]))];
    const pivot = {};
    asc.forEach(r => {
      const m = String(r[timeKey]).slice(0, 7);
      (pivot[m] = pivot[m] || {})[r[dimKey]] = wan(r[volKeys[0]]);
    });
    const palette = ['#1D4ED8', '#3B82F6', '#60A5FA', '#93C5FD', '#BFDBFE', '#16A34A', '#0D9488', '#7C3AED'];
    App.chart(el, {
      tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
      legend: { top: 0, type: 'scroll' },
      grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
      xAxis: { type: 'category', data: months },
      yAxis: { type: 'value', name: '万元' },
      series: dims.map((d, i) => ({
        name: d, type: 'bar', stack: 'v', barMaxWidth: 30,
        itemStyle: { color: palette[i % palette.length] },
        data: months.map(m => (pivot[m] || {})[d]),
      })),
    });
  },
};
