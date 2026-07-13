# 量策 (liangce)

个人量化理财工具箱 —— 基于 Streamlit 的 A 股/基金策略扫描、回测与每日复盘工具。

## 功能概览

- **发现**：用最新行情运行全部内置策略，扫描当日信号
- **板块预测**：行业板块走势预测
- **策略回测**：基于 backtrader 的策略回测
- **参数优化**：基于 optuna 的超参搜索
- **每日市场复盘**：指数概览 / 市场宽度 / 行业热点 / 资金面（带 T+1 数据口径标注与「只述不荐」免责声明）

## 技术栈

- 前端：Streamlit
- 计算：pandas / numpy / plotly
- 回测：backtrader / optuna
- 数据源：akshare、baostock、东方财富直连（`core/em_client.py`，自带 QPS 限流+多域名备胎）、open-stock-data

## 启动

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

Windows / macOS 也可直接双击 `启动量策.bat` / `启动量策.command`。

## 自测验证（数据层 & 功能正确性）

`core/selfcheck.py` 提供一套**离线、纯逻辑**的自测套件，覆盖：

- **数据层正确性**：SQLite 缓存读写/去重/范围查询、行情 DataFrame 归一化（中英文列名兼容、字符串数字数值化、OHLC 约束）、缓存新鲜度判断、演示数据生成；
- **情绪层正确性**：打分 / 否定词反转 / 事件解析 / 加权衰减 / 标签边界 / 相关性过滤；
- **功能正确性（无阻塞）**：12 个策略 + 回测引擎 + 仓位管理必须跑通，且**交易次数 > 0**（交易为 0 视为功能阻塞会报警）；
- **通道诊断**：`diagnose_channels()` 可调用且不抛异常。

运行方式：

```bash
python run_selfcheck.py            # 完整自测，退出码 0=通过
python run_selfcheck.py --quiet    # 仅显示失败项
```

启动脚本（`启动量策.bat` / `启动量策.command`）在启动前会自动跑一次离线自测作为门禁（失败仅告警，不阻断启动）。

## 错误日志收集 & 自动修复

项目内置「静默」错误收集与自动修复（`utils/error_collector.py` + `utils/auto_fix.py`）：

- 任何 `import core` 都会自动挂载全局日志 Handler，把运行期间的 WARNING/ERROR 收集到：
  - 文本日志：`data/error_logs/errors_YYYY-MM-DD.log`
  - 归档库：`data/errors.db`（按指纹去重、记录出现次数与最近 traceback）
- 自动修复（`python -m utils.auto_fix`，或「关于」页的按钮）会扫描未解决错误，按已知规则分类：
  - **可自动修复**（网络超时 / 东财风控 / 数据解析异常）：清理损坏的本地缓存，下次运行重新联网拉取；
  - **环境类已归类**（akshare/baostock/open-stock-data 未安装）：标记并说明，功能已自动降级到备胎源；
  - **需人工关注**：未知类错误，汇总给出消息与建议，保留审计记录。

所有自动动作均为**低风险、可逆**（仅清理本地缓存、标记记录，绝不修改业务源码、绝不删除归档历史）。日常使用无需手动提醒，系统会自行收集并在「关于 → 🛠️ 系统自检 & 错误日志修复」面板展示。

## 许可证

本项目以 **GNU General Public License v3.0 (GPL-3.0)** 发布。

- 许可证全文见 [LICENSE](./LICENSE)
- 你可以自由使用、修改、分发本软件，但任何衍生作品也**必须以 GPL-3.0 开源**
- 本软件**不提供任何担保**（详见 LICENSE 第 15、16 条）

## 第三方方法论借鉴说明

本项目在「每日市场复盘」模块的方法论上借鉴了以下以 **GPL-3.0** 发布的开源项目，
并已依据该许可证合法复用其思路（**未拷贝其任何代码、未引入其专有数据源 Pandadata**）：

- [quantskills/skill-market-daily-review](https://github.com/quantskills/skill-market-daily-review)
  —— 借鉴其「章节→数据」组织结构与 T+1 标注、优雅降级不估数原则
- [quantskills/skill-futures-deepview-analyst](https://github.com/quantskills/skill-futures-deepview-analyst)
  —— 借鉴其「事实≠推断」分离、同日对齐、席位口径声明的报告规范（期货模块规划中）

由于本项目同样以 GPL-3.0 发布，符合上述项目的许可证要求。

## 免责声明

本工具仅用于量化研究与学习，**所有市场数据、策略信号、复盘内容均只作客观陈述，
不构成任何投资建议**。投资有风险，决策需谨慎。
