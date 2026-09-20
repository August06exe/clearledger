// 明账 ClearLedger — API 访问与轻提示
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
  } catch (e) {
    Toast.show('无法连接门户后端：' + e.message, true);
    throw e;
  }
  if (!res.ok) {
    let msg = res.statusText;
    let detail = null;
    try { const j = await res.json(); msg = j.detail || msg; detail = j.detail; } catch (_) {}
    Toast.show(typeof msg === 'object' ? '请求被拒绝' : msg, res.status >= 500);
    const err = new Error(typeof msg === 'object' ? JSON.stringify(msg) : msg);
    err.detail = detail;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

const Toast = {
  timer: null,
  show(msg, isErr = false) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = isErr ? 'err show' : 'show';
    clearTimeout(Toast.timer);
    Toast.timer = setTimeout(() => { el.className = ''; }, 3600);
  },
};
