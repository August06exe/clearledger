// 明账 ClearLedger — AI 接入页：这个系统以 agent 为第一操作者
window.Pages.ai = {
  AGENT_CMD: '读取仓库根目录的 docs/AI-点火指南.md 与 AGENTS.md，' +
             '然后接管这个明账实例：帮我初始化并跑起来，之后负责日常维护与修错。',

  MCP_JSON: '{ "mcpServers": { "clearledger": {\n' +
    '    "command": "C:/path/to/clearledger/.venv/Scripts/python.exe",\n' +
    '    "args": ["C:/path/to/clearledger/mcp_server.py"] } } }',

  async render(container) {
    container.innerHTML = `
      <div class="card ai-hero">
        <div class="ai-hero-title">🤖 明账是 AI-Native 的数据底座</div>
        <div class="ai-hero-sub">
          一切随公司变化的东西都在六份纯文本 YAML 里，脚本与管道的搭建、改配置、修报错，
          都设计为交给 agent 完成。你负责丢文件、定口径、看红绿灯。
        </div>
      </div>

      <div class="card ai-card">
        <h3>① 把仓库交给你的 coding agent（推荐）</h3>
        <div class="muted" style="margin:8px 0 10px">
          ZCode、Claude Code、Cursor 等任意 agent，在仓库根目录对它说：
        </div>
        <div class="ai-cmd-wrap">
          <pre id="ai-cmd" class="ai-cmd"></pre>
          <button class="btn ai-copy" data-copy="ai-cmd">复制</button>
        </div>
        <div class="muted2" style="margin-top:8px">
          点火指南会带它完成：环境自举 → 演示数据 → 首次跑批 → 门户验收，全程有检查点。
        </div>
      </div>

      <div class="card ai-card">
        <h3>② 让常驻 agent 直连（MCP · 只读 · 全程审计）</h3>
        <div class="muted" style="margin:8px 0 10px">
          六个只读工具：账套/指标目录/报表查询（仅声明维度×指标，明细行架构上摸不到）/
          数据健康诊断/口径查询。把下面的配置加进你 agent 客户端的 MCP 设置（路径改成你的仓库位置）：
        </div>
        <div class="ai-cmd-wrap">
          <pre id="ai-mcp" class="ai-cmd"></pre>
          <button class="btn ai-copy" data-copy="ai-mcp">复制</button>
        </div>
      </div>

      <div class="card ai-card">
        <h3>③ HTTP 开放接口</h3>
        <div class="muted" style="margin:8px 0">
          不走 MCP 的系统用 HTTP 也行：在 <code>data/openapi_keys.json</code> 配钥匙
          （模板见 <code>openapi_keys.example.json</code>），带 <code>X-API-Key</code>
          调用 <code>/api/open/*</code>。每次调用都有审计留痕。
        </div>
      </div>

      <div class="card ai-card">
        <h3>④ 首开提醒</h3>
        <label class="row" style="gap:8px;font-size:14px">
          <input type="checkbox" id="ai-banner-switch">
          打开门户时显示「AI 接入」提醒横幅
        </label>
      </div>

      <div class="muted2" style="padding:0 4px 20px">
        完整指引：<code>docs/AI-点火指南.md</code>（点火与初始化，写给 agent 读）·
        <code>docs/AI-操作手册.md</code>（日常维护配方）· <code>AGENTS.md</code>（工程章程与红线）
      </div>`;

    document.getElementById('ai-cmd').textContent = this.AGENT_CMD;
    document.getElementById('ai-mcp').textContent = this.MCP_JSON;

    container.querySelectorAll('.ai-copy').forEach(btn =>
      btn.addEventListener('click', async () => {
        const text = document.getElementById(btn.dataset.copy).textContent;
        try {
          await navigator.clipboard.writeText(text);
          btn.textContent = '已复制 ✓';
          setTimeout(() => { btn.textContent = '复制'; }, 1500);
        } catch (_) { Toast.show('复制失败，请手动选择文本'); }
      }));

    const sw = document.getElementById('ai-banner-switch');
    let s = {};
    try { s = await api('/api/settings'); } catch (_) {}
    sw.checked = s.ai_banner !== false;
    sw.addEventListener('change', async () => {
      try {
        await api('/api/settings', { method: 'POST', body: JSON.stringify({ ai_banner: sw.checked }) });
        Toast.show(sw.checked ? '首开提醒已开启' : '首开提醒已关闭');
        const b = document.getElementById('ai-banner');
        if (b && !sw.checked) b.remove();
      } catch (_) { sw.checked = !sw.checked; }
    });
  },
};
