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
