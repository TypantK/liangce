# 跨平台开发注意事项（macOS / Windows）

本项目需同时支持 macOS 与 Windows 运行。以下为开发时务必留意的坑与约定。

## 1. Streamlit 图表内快捷键（Q/W/E/A/S 等）失效问题

### 现象
图表（`pages/backtest_page.py` 的 `_build_chart_html`）通过 `st.components.v1.html` 注入，
快捷键由注入的 JS `keydown` 监听实现。在 macOS 上正常，但在 Windows 上按键无反应。

### 根因
`st.components.v1.html` 把内容渲染进一个 `<iframe>`。快捷键原本只监听了 **iframe 内部的
`document`**。当焦点停留在父页面（Streamlit 主框架）时，Windows 下按键事件不会冒泡到 iframe，
导致监听收不到事件；macOS 上因焦点管理差异偶然能用，属于"假正常"。

### 修复约定（已修复）
在注入脚本中 **同时监听父页面（顶层 frame）的 keydown 并转发**到同一个处理函数：

```js
// iframe 内焦点
document.addEventListener('keydown', handleHotkey);
// 父页面焦点（跨平台关键）
try {
  if (window.top && window.top !== window.self) {
    window.top.addEventListener('keydown', handleHotkey);
  }
} catch (err) { /* 跨域限制忽略 */ }
```

后续新增任何图表内键盘交互，都必须同时绑定 `document` 与 `window.top`，否则 Windows 必现失效。

### 额外健壮性
- 处理函数开头过滤组合键：`if (e.ctrlKey || e.metaKey || e.altKey) return;`，避免劫持系统快捷键。
- 用 `e.key`（而非 `e.keyCode`）判断，注意 `e.key` 可能为空，需 `|| ''` 兜底再 `toLowerCase()`。
- 输入框/文本域聚焦时不触发：`/^(INPUT|TEXTAREA|SELECT)$/.test(activeElement.tagName)`。

## 2. 通用跨平台约定

- **路径分隔符**：一律用 `pathlib.Path` / `os.path.join`，禁止硬编码 `\\` 或 `/`。
- **换行符**：文件写入避免依赖 `\r\n`，文本模式打开即可（Python 自动处理）。
- **字体**：图表字体用 `'PingFang SC, Microsoft YaHei, SimHei, Arial Unicode MS, sans-serif'`
  这类跨平台回退链（项目 `CN_FONT` 常量已定义，复用它）。
- **启动脚本**：仓库根目录 `启动量策.command` 为 macOS 脚本；Windows 用户请用
  `python -m streamlit run app.py`。如需 Windows 启动器，可新增 `启动量策.bat`。
- **依赖**：以 `requirements.txt` 为准，保持两平台版本一致；不要引入仅某平台可用的原生包。
- **编码**：所有文件统一 UTF-8（含读写时显式 `encoding='utf-8'`）。
