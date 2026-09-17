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
    try { const j = await res.json(); msg = j.detail || msg; } catch (_) {}
    Toast.show(msg, res.status >= 500);
    throw new Error(msg);
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
