// 管理报表页：报表列表 + 参数筛选 + 图表 + 明细表 + Excel 导出
window.Pages.reports = {
  async render(el, key) {
    const data = await api('/api/reports');
    this.options = data.options || {};
    const reports = data.reports || [];
    if (!key || !reports.find(r => r.key === key)) key = reports[0] && reports[0].key;
    this.key = key;

    el.innerHTML = `
      <div id="report-wrap">
        <div id="report-list">
          ${reports.map(r => `
            <div class="report-item ${r.key === key ? 'active' : ''}" data-key="${r.key}">
              <div class="t">${r.title}</div>
              <div class="d">${r.description}</div>
            </div>`).join('')}
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
    const meta = (await api('/api/reports')).reports.find(r => r.key === this.key);
    if (!meta) { main.innerHTML = '<div class="empty-tip">报表不存在</div>'; return; }

    // 参数栏
    const paramsHtml = (meta.params || []).map(p => {
      if (p.type === 'select') {
        const opts = this.options[p.options_from] || [];
        return `<div><label>${p.label}</label>
          <select data-param="${p.name}">
            <option value="">全部</option>
            ${opts.map(o => `<option value="${o}" ${p.default === o ? 'selected' : ''}>${o}</option>`).join('')}
          </select></div>`;
      }
      return `<div><label>${p.label}</label>
        <input type="number" data-param="${p.name}" value="${p.default ?? ''}" min="1" max="36" style="width:90px"></div>`;
    }).join('');

    main.innerHTML = `
      <div class="row spread">
        <h3 style="margin:0">${meta.title}</h3>
        <div class="row">
          <button id="rp-query" class="btn btn-primary btn-sm">查询</button>
          <button id="rp-export" class="btn btn-sm">⬇ 导出 Excel</button>
        </div>
      </div>
      <div class="muted mt8">${meta.description}</div>
      <div class="param-bar mt16">${paramsHtml}</div>
      <div id="rp-chart" class="chart"></div>
      <div id="rp-table" class="mt16" style="max-height:420px;overflow:auto"></div>`;

    document.getElementById('rp-query').addEventListener('click', () => this.query(meta));
    document.getElementById('rp-export').addEventListener('click', () => {
      window.open('/api/reports/' + this.key + '/export?' + this.qs(), '_blank');
    });
    this.query(meta);
  },

  qs() {
    const params = [];
    document.querySelectorAll('#report-main [data-param]').forEach(inp => {
      const v = inp.value;
      if (v !== '' && v !== null && v !== undefined) params.push(`${inp.dataset.param}=${encodeURIComponent(v)}`);
    });
    return params.join('&');
  },

  async query(meta) {
    const table = document.getElementById('rp-table');
    try {
      const r = await api(`/api/reports/${this.key}/data?` + this.qs());
      this.last = r;
      const cols = r.columns || [];
      if (!r.rows.length) {
        table.innerHTML = '<div class="empty-tip">没有数据（试试调大月数）</div>';
      } else {
        table.innerHTML = `
          <table class="tbl"><thead><tr>
            ${cols.map(([, label]) => `<th class="${this.isNum(label) ? 'num' : ''}">${label}</th>`).join('')}
          </tr></thead>
          <tbody>${r.rows.map(row => `<tr>
            ${cols.map(([key, label]) => `<td class="${this.isNum(label) ? 'num' : ''}">${this.fmtCell(label, row[key])}</td>`).join('')}
          </tr>`).join('')}</tbody></table>`;
      }
      this.drawChart(cols, r.rows);
    } catch (_) {
      table.innerHTML = '<div class="empty-tip">查询失败（可能正在跑批，稍后再试）</div>';
    }
  },

  isNum(label) {
    return !['月份', '区域', '行业', '客户等级', '状态', '部门名称', '部门编码', '费用类别',
      '品类', '商品编号', '商品名称', '客户名称', '客户编号', '最近下单'].includes(label);
  },

  fmtCell(label, v) {
    if (v === null || v === undefined) return '—';
    if (label.includes('率') || label.includes('环比')) return Fmt.pct(v);
    if (!this.isNum(label)) return label === '月份' ? String(v).slice(0, 7) : String(v);
    return Fmt.yuan(v);
  },

  drawChart(cols, rows) {
    const el = document.getElementById('rp-chart');
    if (!el || !rows.length) { if (el) el.style.display = 'none'; return; }
    el.style.display = '';
    const keyOf = label => (cols.find(([k, l]) => l === label) || [])[0];
    const monthKey = keyOf('月份');
    const asc = rows.slice().sort((a, b) => String(a.month).localeCompare(String(b.month)));
    const months = [...new Set(asc.map(r => String(r.month).slice(0, 7)))];
    const wan = v => v === null || v === undefined ? null : +(v / 1e4).toFixed(1);

    let option = null;
    if (this.key === 'monthly_kpi') {
      option = {
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        grid: { left: 8, right: 40, top: 34, bottom: 0, containLabel: true },
        xAxis: { type: 'category', data: months },
        yAxis: [{ type: 'value', name: '万元' }, { type: 'value', name: '%', position: 'right', axisLabel: { formatter: '{value}%' } }],
        series: [
          { name: '收入', type: 'bar', barMaxWidth: 24, itemStyle: { color: '#3B82F6', borderRadius: [4, 4, 0, 0] }, data: asc.map(r => wan(r.revenue)) },
          { name: '毛利', type: 'bar', barMaxWidth: 24, itemStyle: { color: '#93C5FD', borderRadius: [4, 4, 0, 0] }, data: asc.map(r => wan(r.gross_profit)) },
          { name: '净利', type: 'line', smooth: true, itemStyle: { color: '#16A34A' }, data: asc.map(r => wan(r.net_profit)) },
          { name: '毛利率', type: 'line', yAxisIndex: 1, smooth: true, itemStyle: { color: '#D97706' }, data: asc.map(r => r.gross_margin === null ? null : +(r.gross_margin * 100).toFixed(1)) },
        ],
      };
    } else if (this.key === 'region_month') {
      const regions = [...new Set(asc.map(r => r.region_name))];
      const pivot = {};
      asc.forEach(r => {
        const m = String(r.month).slice(0, 7);
        (pivot[m] = pivot[m] || {})[r.region_name] = wan(r.revenue);
      });
      option = {
        tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
        legend: { top: 0 },
        grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
        xAxis: { type: 'category', data: months },
        yAxis: { type: 'value', name: '万元' },
        series: regions.map((rg, i) => ({
          name: rg, type: 'bar', stack: 'revenue', barMaxWidth: 30,
          itemStyle: { color: ['#1D4ED8', '#3B82F6', '#60A5FA', '#93C5FD', '#BFDBFE'][i % 5] },
          data: months.map(m => (pivot[m] || {})[rg]),
        })),
      };
    } else if (this.key === 'customer_summary') {
      const top = rows.slice(0, 15).slice().reverse();
      option = {
        tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
        grid: { left: 8, right: 30, top: 10, bottom: 0, containLabel: true },
        xAxis: { type: 'value', name: '万元' },
        yAxis: { type: 'category', data: top.map(r => r.customer_name), axisLabel: { fontSize: 11 } },
        series: [{ type: 'bar', barMaxWidth: 14, itemStyle: { color: '#1D4ED8', borderRadius: [0, 4, 4, 0] }, data: top.map(r => wan(r.ltm_revenue)) }],
      };
    } else if (this.key === 'product_month') {
      const cats = [...new Set(asc.map(r => r.category))];
      const pivot = {};
      asc.forEach(r => {
        const m = String(r.month).slice(0, 7);
        (pivot[m] = pivot[m] || {})[r.category] = (pivot[m] || {})[r.category] + r.revenue || r.revenue;
      });
      option = {
        tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
        legend: { top: 0 },
        grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
        xAxis: { type: 'category', data: months },
        yAxis: { type: 'value', name: '万元' },
        series: cats.map((c, i) => ({
          name: c, type: 'bar', stack: 'rev', barMaxWidth: 30,
          itemStyle: { color: ['#1D4ED8', '#16A34A', '#D97706', '#7C3AED', '#0891B2'][i % 5] },
          data: months.map(m => wan((pivot[m] || {})[c])),
        })),
      };
    } else if (this.key === 'expense_dept_month') {
      const cats = [...new Set(asc.map(r => r.category))];
      const pivot = {};
      asc.forEach(r => {
        const m = String(r.month).slice(0, 7);
        (pivot[m] = pivot[m] || {})[r.category] = (pivot[m] || {})[r.category] + r.allocated_amount || r.allocated_amount;
      });
      option = {
        tooltip: { trigger: 'axis', valueFormatter: v => v + ' 万' },
        legend: { top: 0, type: 'scroll' },
        grid: { left: 8, right: 8, top: 34, bottom: 0, containLabel: true },
        xAxis: { type: 'category', data: months },
        yAxis: { type: 'value', name: '万元' },
        series: cats.map((c, i) => ({
          name: c, type: 'bar', stack: 'exp', barMaxWidth: 30,
          itemStyle: { color: ['#1D4ED8', '#3B82F6', '#7C3AED', '#0891B2', '#D97706', '#65A30D'][i % 6] },
          data: months.map(m => wan((pivot[m] || {})[c])),
        })),
      };
    }

    if (option) App.chart(el, option);
    else el.style.display = 'none';
  },
};
