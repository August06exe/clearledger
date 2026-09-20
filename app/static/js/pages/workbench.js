// 明账 ClearLedger — 配置工作台（v0.5）：六块配置 编辑/校验/保存/重建 + 挂起队列 + 影响预览
window.Pages.workbench = {
  BLOCKS: [
    { key: 'instance', label: '账套元信息' },
    { key: 'sources', label: '① 数据源' },
    { key: 'wide', label: '② 宽表' },
    { key: 'dimensions', label: '③ 维度' },
    { key: 'metrics', label: '④ 指标' },
    { key: 'dashboard', label: '⑤ 看板' },
  ],
  tab: 'editor',

  async render(container) {
    container.innerHTML = `
      <div class="wb-tabs">
        <button class="btn wb-tab active" data-tab="editor">配置编辑</button>
        <button class="btn wb-tab" data-tab="pending">挂起队列</button>
      </div>
      <div id="wb-body"></div>`;
    container.querySelectorAll('.wb-tab').forEach(b =>
      b.addEventListener('click', () => {
        this.tab = b.dataset.tab;
        container.querySelectorAll('.wb-tab').forEach(x => x.classList.toggle('active', x === b));
        this.renderTab();
      }));
    this.el = document.getElementById('wb-body');
    await this.renderTab();
  },

  async renderTab() {
    if (this.tab === 'pending') return this.renderPending();
    return this.renderEditor();
  },

  async renderEditor(selectBlock) {
    let ov;
    try { ov = await api('/api/instance'); } catch (_) { return; }
    const inst = ov.current;
    let overview = { blocks: [], title: inst };
    try { overview = await api('/api/config/' + inst); } catch (_) {}
    const blocks = overview.blocks || [];
    const cur = selectBlock || this._curBlock && blocks.some(b => b.block === this._curBlock)
      ? (selectBlock || this._curBlock) : (blocks.find(b => b.exists) || {}).block;
    this.el.innerHTML = `
      <div class="wb-layout">
        <div class="wb-side card">
          <div class="muted" style="padding:8px 12px 4px">账套【${overview.title || inst}】六块配置</div>
          ${blocks.map(b => `
            <div class="wb-block ${b.block === cur ? 'active' : ''} ${b.exists ? '' : 'wb-missing'}"
                 data-block="${b.block}">
              <div>${(this.BLOCKS.find(x => x.key === b.block) || {}).label || b.block}</div>
              <div class="muted2" style="font-size:11px">${b.file} · ${b.exists ? Math.ceil(b.size / 102.4) / 10 + ' KB' : '缺失'}</div>
            </div>`).join('')}
          <div class="muted2" style="padding:10px 12px;font-size:11px;line-height:1.6">
            保存前自动校验；旧文件滚动备份到 onboarding/config_history/。改口径 = 改 metrics，保存并重建即生效。
          </div>
        </div>
        <div class="wb-main">
          <div class="row" style="gap:8px;margin-bottom:8px">
            <button class="btn" id="wb-validate">✓ 校验</button>
            <button class="btn" id="wb-save">保存</button>
            <button class="btn btn-primary" id="wb-save-rebuild">保存并重建</button>
            <span id="wb-status" class="muted"></span>
          </div>
          <textarea id="wb-editor" class="wb-editor" spellcheck="false"></textarea>
          <div id="wb-result"></div>
        </div>
      </div>`;
    this.el.querySelectorAll('.wb-block').forEach(el =>
      el.addEventListener('click', () => this.renderEditor(el.dataset.block)));
    this.el.querySelector('#wb-validate').addEventListener('click', () => this.doValidate(false));
    this.el.querySelector('#wb-save').addEventListener('click', () => this.doSave(false));
    this.el.querySelector('#wb-save-rebuild').addEventListener('click', () => this.doSave(true));
    this._curBlock = cur;
    await this.loadContent();
  },

  async loadContent() {
    if (!this._curBlock) return;
    try {
      const d = await api(`/api/config/${await this.inst()}/${this._curBlock}`);
      const ta = document.getElementById('wb-editor');
      ta.value = d.content || '';
      this.showResult(d.parsed_ok ? null : { errors: ['YAML 解析失败: ' + d.parse_error] }, 'warn');
    } catch (e) {
      document.getElementById('wb-editor').value = '';
      this.showResult({ errors: ['读取失败：' + (e && e.message || e)] }, 'bad');
    }
  },

  async inst() {
    if (this._inst) return this._inst;
    const ov = await api('/api/instance');
    this._inst = ov.current;
    return this._inst;
  },

  content() { return document.getElementById('wb-editor').value; },
  setStatus(t) { const el = document.getElementById('wb-status'); if (el) el.textContent = t || ''; },

  showResult(res, tone) {
    const box = document.getElementById('wb-result');
    if (!box) return;
    if (!res) { box.innerHTML = ''; return; }
    const errs = res.errors || [];
    if (tone === 'warn' || errs.length) {
      box.innerHTML = `<div class="wb-result bad"><b>✗ ${errs.length} 个问题</b>
        <ul>${errs.map(e => `<li>${e}</li>`).join('')}</ul></div>`;
    } else if (tone === 'ok') {
      box.innerHTML = `<div class="wb-result good"><b>✓ 校验通过</b>${res.affectedText || ''}</div>`;
    } else { box.innerHTML = ''; }
  },

  async doValidate() {
    this.setStatus('校验中…');
    let r;
    try {
      r = await api(`/api/config/${await this.inst()}/${this._curBlock}/validate`,
        { method: 'POST', body: JSON.stringify({ content: this.content() }) });
    } catch (e) {
      this.showResult({ errors: this.errList(e) });
      this.setStatus('校验未通过');
      return;
    }
    this.showResult(r, r.ok ? 'ok' : undefined);
    this.setStatus(r.ok ? '校验通过' : '校验未通过');
  },

  errList(e) {
    const d = e && e.detail;
    if (d && Array.isArray(d.errors)) return d.errors;
    if (Array.isArray(d)) return d;
    if (typeof d === 'string') return [d];
    return [String((e && e.message) || e)];
  },

  async doSave(rebuild) {
    if (rebuild && !confirm('保存并触发重新编译+跑批？改错的配置会让跑批变红。')) return;
    this.setStatus(rebuild ? '保存并重建中…' : '保存中…');
    let r;
    try {
      r = await api(`/api/config/${await this.inst()}/${this._curBlock}/save`,
        { method: 'POST', body: JSON.stringify({ content: this.content(), rebuild }) });
    } catch (e) {
      this.showResult({ errors: this.errList(e) });
      this.setStatus('保存被拒绝（未落盘）');
      return;
    }
    const aff = (r.affected_reports || []);
    Toast.show(`已保存 ${this._curBlock}` + (aff.length ? ` · 影响 ${aff.length} 张报表：${aff.join('、')}` : ''));
    if (r.rebuild && r.rebuild.triggered) {
      Toast.show('重建已启动：' + r.rebuild.run_id);
      App.triggerRun();   // 复用顶栏轮询，跑完自动刷新红绿灯
    } else if (r.rebuild && r.rebuild.reason === 'run_in_progress') {
      Toast.show('已有跑批在进行，未重复触发', true);
    }
    this.showResult({ errors: [] }, 'ok');
    this.setStatus('已保存' + (rebuild ? '，重建进行中' : ''));
    this.renderEditor(this._curBlock);
    // 重渲染后 result 会被清掉，补一次提示
    setTimeout(() => this.showResult({ errors: [] }, 'ok'), 50);
  },

  async renderPending() {
    this.el.innerHTML = '<div class="empty-tip">加载中…</div>';
    let d;
    try { d = await api(`/api/config/${await this.inst()}/pending`); }
    catch (e) { this.el.innerHTML = `<div class="empty-tip">加载失败：${e.message || e}</div>`; return; }
    if (d.note === 'no_db' || !d.items || !d.items.length) {
      this.el.innerHTML = `<div class="card" style="padding:24px"><b>挂起队列为空</b>
        <div class="muted" style="margin-top:6px">最近一次跑批没有需要人工介入的契约问题。${d.note === 'no_db' ? '（该账套还没有库文件，先跑一次批）' : ''}</div></div>`;
      return;
    }
    const LR = { red: '失', yellow: '警', pending: '待', green: '正' };
    this.el.innerHTML = `
      <div class="card" style="padding:16px 20px">
        <div class="row spread" style="margin-bottom:10px">
          <b>挂起队列 · 最近一次跑批 ${d.latest_run ? Fmt.dt(d.latest_run.finished_at) : ''}</b>
          <span class="muted">${d.items.length} 项待处理</span>
        </div>
        <table class="tbl">
          <thead><tr><th style="width:70px">级别</th><th style="width:160px">数据源</th><th style="width:160px">字段</th>
          <th style="width:140px">规则</th><th class="num" style="width:80px">行数</th><th>样例</th></tr></thead>
          <tbody>
            ${d.items.map(it => `
              <tr>
                <td><span class="light light-${it.level === 'pending' ? 'yellow' : it.level}"><i></i>${LR[it.level] || it.level}</span></td>
                <td>${it.source}</td><td>${it.field}</td><td>${it.rule}</td>
                <td class="num">${it.cnt}</td><td class="muted">${it.sample || '—'}</td>
              </tr>`).join('')}
          </tbody>
        </table>
        <div class="muted2" style="margin-top:10px">处理方式：修数据重投 → 重新跑批；或在「配置编辑」里放宽该字段契约（level 改 yellow/ignore）后保存并重建。</div>
      </div>`;
  },
};
