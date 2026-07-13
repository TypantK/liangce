# 跨平台开发注意事项（macOS / Windows）

本项目需同时支持 macOS 与 Windows 运行。以下为开发时务必留意的坑与约定。

## 1. Streamlit 图表内快捷键（Q/W/E/A/S）与点击/双击 K 线

### 需求
所有图表（回测 K 线、基金回测、板块预测、参数优化热力图）统一支持：
- 点击 K 线/折线 → 以该点为中心放大 60 天窗口
- 双击主图 → 放大；双击空白 → 重置全览
- 快捷键（焦点在图表内或父页面均可生效）：
  `Q`=缩放  `W`=平移  `E`=全览  `A`=放大  `S`=缩小

### 统一实现（务必复用，勿各自造轮子）
所有图表渲染都走 `utils/chart.py` 的两个共享函数：

```python
from utils.chart import build_enhanced_chart_html, inject_hotkey_bridge_once

chart_html = build_enhanced_chart_html(fig, version=..., theme=theme, auto_zoom=False)
inject_hotkey_bridge_once()                       # 注入父页桥接（整页一次）
st.components.v1.html(chart_html, height=...)    # 渲染进 iframe
```

> ⚠️ 禁止再用 `st.plotly_chart` 渲染需要快捷键/点击放大的图表——
> 它走 Streamlit 自带 iframe，无法注入我们的增强 JS，会导致功能缺失（历史 bug）。
> 若只需静态展示、无需交互增强，才可用 `st.plotly_chart`。

### 跨平台生效原理（为何 Windows 之前失效）
- 图表通过 `st.components.v1.html` 渲染进一个 `<iframe>`，增强 JS 运行在 iframe 内部，
  能正确访问图表对象 `gd` 与 `Plotly`。
- **macOS**：默认焦点落在 iframe 内，iframe 自身的 `document` keydown 监听即可生效。
- **Windows**：焦点常停留在父页面（Streamlit 主框架），按键事件不冒泡进 iframe → 失效。

正确做法（当前方案）：
1. iframe 内部：监听自身 `document` keydown **且** 监听 `window` 的 `message` 事件。
2. 父页面桥接：通过 `st.markdown(..., unsafe_allow_html=True)` 注入到**真正的父页面上下文**
   （`inject_hotkey_bridge_once` 内实现），在父页 `document` 捕获 keydown，过滤输入框后
   `postMessage` 给图表 iframe（`srcdoc` 含 `__chartHotkey` 标记的那个）。
3. iframe 收到 `postMessage` 后在**正确上下文**执行 `handleHotkey`。

> 历史坑：曾把"父页桥接"错误地写进 `_build_chart_html` 返回的 iframe HTML 里，
> 它运行在 iframe 上下文、找不到父页面的 `iframe[srcdoc]`，等于无效。
> 桥接脚本必须经由 `st.markdown` 注入父页面。

### 健壮性要点
- 处理函数过滤 `ctrl/meta/alt` 组合键，避免劫持系统快捷键。
- 过滤 `e.isComposing`（中文输入法合成中），避免误触。
- 仅在焦点不在 `INPUT/TEXTAREA/SELECT` 时触发。
- 用 `e.key`（不是 `keyCode`），并 `|| ''` 兜底再 `toLowerCase()`。
- `tryInit` 用多种选择器兜底获取 Plotly div：`#chart_id` / `.js-plotly-plot` /
  `.plotly-graph-div` / `[id^="chart_"]`，并监听 `plotly_afterplot` 确保绑定成功。
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
