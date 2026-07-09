# 跨平台开发注意事项（macOS / Windows）

本项目需同时支持 macOS 与 Windows 运行。以下为开发时务必留意的坑与约定。

## 1. Streamlit 图表内快捷键（Q/W/E/A/S 等）失效问题

### 现象
图表（`pages/backtest_page.py` 的 `_build_chart_html`）通过 `st.components.v1.html` 注入，
快捷键由注入的 JS `keydown` 监听实现。**该方案在 macOS 与 Windows 上均应生效**（已验证）。

### 根因
`st.components.v1.html` 把内容渲染进一个 `<iframe>`。快捷键原本只监听了 **iframe 内部的
`document`**。当焦点停留在父页面（Streamlit 主框架）时，Windows 下按键事件不会冒泡到 iframe，
导致监听收不到事件；macOS 上因焦点管理差异偶然能用，属于"假正常"。

### 修复约定（已修复 — v2）
旧方案直接在 `window.top` 上 `addEventListener('keydown', handleHotkey)` 并就地执行。
**该方案在 Windows 上失效的根因**：`handleHotkey` 内部通过 `window.__chartDebug.getGd()`
访问图表对象 `gd`，但 `window.__chartDebug` 挂在 **iframe 内部** 的 `window` 上；
父页面转发的事件回调在父页面上下文执行，访问到的 `window.__chartDebug` 为 `undefined`
→ `gd` 为 `undefined` → 直接 return，快捷键永远不生效。这是上下文错位，并非焦点问题。

正确做法：**用 `postMessage` 把按键从父页面转发进 iframe，由 iframe 内部（能正确
访问 `gd` / `Plotly`）执行处理函数**。

```js
// —— iframe 内部（_build_chart_html 第二个 <script>）——
window.addEventListener('message', function(ev) {
  var d = ev.data;
  if (!d || d.__chartHotkey !== true) return;
  handleHotkey({ key: d.key, ctrlKey: d.ctrlKey, metaKey: d.metaKey, altKey: d.altKey,
                 preventDefault: function(){} });
});

// —— 父页面桥接（_build_chart_html 第三个 <script>）——
// 在父页面 document 上捕获 keydown（捕获阶段），过滤输入框后 postMessage 给图表 iframe
document.addEventListener('keydown', function(e) {
  var tag = (document.activeElement || {}).tagName || '';
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
  var frame = document.querySelector('iframe[id^="chart_"]') || ...;
  frame.contentWindow.postMessage({ __chartHotkey: true, key: e.key, ... }, '*');
}, true);
```

后续新增任何图表内键盘交互，都必须走 `postMessage` 转发 + iframe 内执行，否则 Windows 必现失效。
**切勿再用 `window.top.addEventListener` 直接调用依赖 iframe 内部变量的函数。**

### 额外健壮性
- 处理函数开头过滤组合键：`if (e.ctrlKey || e.metaKey || e.altKey) return;`，避免劫持系统快捷键。
  （注意：macOS 的 Cmd 对应 `metaKey`、Windows 的 Ctrl 对应 `ctrlKey`，两者都会被这条拦截，
  而**单键 Q/W/E/A/S 在双平台都不带修饰键，因此都能正常触发**。）
- **输入法合成态过滤（双平台必加）**：中文/日文输入法激活时，浏览器会把按键标记为
  `e.isComposing === true`（部分旧内核 `e.key === 'Process'`）。必须 `if (e.isComposing || e.key === 'Process') return;`
  否则 Mac/Windows 在中文输入法下快捷键会失效或误触。
- 用 `e.key`（而非 `e.keyCode`）判断，注意 `e.key` 可能为空，需 `|| ''` 兜底再 `toLowerCase()`。
  （Caps Lock / Shift 状态下 `e.key` 会是 `'Q'`，`toLowerCase()` 已归一。）
- 输入框/文本域聚焦时不触发：`/^(INPUT|TEXTAREA|SELECT)$/.test(activeElement.tagName)`。
- 跨 frame 通信用 `postMessage(ev, '*')` 即可（同源 Streamlit 运行时无跨域限制）；
  不要在父页回调里直接访问 iframe 的 `window` 变量。

## 2. 通用跨平台约定

- **路径分隔符**：一律用 `pathlib.Path` / `os.path.join`，禁止硬编码 `\\` 或 `/`。
- **换行符**：文件写入避免依赖 `\r\n`，文本模式打开即可（Python 自动处理）。
- **字体**：图表字体用 `'PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif'`
  这类跨平台回退链（项目 `CN_FONT` 常量已定义，复用它）。
- **启动脚本**：仓库根目录 `启动量策.command` 为 macOS 脚本；Windows 用户请用
  `python -m streamlit run app.py`。如需 Windows 启动器，可新增 `启动量策.bat`。
- **依赖**：以 `requirements.txt` 为准，保持两平台版本一致；不要引入仅某平台可用的原生包。
- **编码**：所有文件统一 UTF-8（含读写时显式 `encoding='utf-8'`）。
