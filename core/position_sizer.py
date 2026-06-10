# -*- coding: utf-8 -*-
"""
仓位管理器 — 与策略解耦的独立仓位计算模块

每种 Sizer 提供统一的 calc_size(cash, price, **kwargs) 接口，
由策略在买入时调用，决定本次买入多少股。
"""


class BaseSizer:
    """仓位管理器基类 — 统一接口"""

    def calc_size(self, cash, price, **kwargs):
        """返回应买入的股数（整数），子类必须实现"""
        raise NotImplementedError


# ============================================================
#  1. 固定比例 — 每次用现金的指定百分比买入
# ============================================================
class FixedFractionSizer(BaseSizer):
    """固定比例仓位：size = cash * fraction / price"""

    def __init__(self, fraction=0.95):
        self.fraction = fraction

    def calc_size(self, cash, price, **kwargs):
        return cash * self.fraction / price


# ============================================================
#  2. 凯利公式 — f = (p*b - q) / b
# ============================================================
class KellySizer(BaseSizer):
    """
    凯利公式仓位：
      f = (p * b - q) / b
      其中 p = 胜率, q = 1 - p, b = 平均盈利 / 平均亏损
      半凯利将 f 减半以降低波动
    """

    def __init__(self, win_rate=0.5, avg_win=0.03, avg_loss=0.02, half_kelly=False):
        self.win_rate = win_rate
        self.avg_win = avg_win
        self.avg_loss = avg_loss
        self.half_kelly = half_kelly

    def calc_size(self, cash, price, **kwargs):
        p = self.win_rate
        q = 1.0 - p
        b = self.avg_win / self.avg_loss if self.avg_loss > 0 else 1.0
        f = (p * b - q) / b if b > 0 else 0.0
        f = max(0.0, min(f, 1.0))          # 裁剪到 [0, 1]
        if self.half_kelly:
            f = f / 2.0
        return cash * f / price


# ============================================================
#  3. ATR 波动率调整 — size = (cash * risk_pct) / (n * ATR)
# ============================================================
class ATRSizer(BaseSizer):
    """
    ATR 波动率调整仓位：
      size = (cash * risk_pct) / (atr_multiplier * ATR)
      ATR 越大 → 波动越大 → 仓位越小
      kwargs 可传入 atr 覆盖默认推算
    """

    def __init__(self, risk_pct=0.02, atr_multiplier=2.0):
        self.risk_pct = risk_pct
        self.atr_multiplier = atr_multiplier

    def calc_size(self, cash, price, **kwargs):
        atr = kwargs.get('atr', price * 0.02)   # 默认按价格 2% 估算
        if atr <= 0:
            return 0
        return (cash * self.risk_pct) / (self.atr_multiplier * atr)


# ============================================================
#  4. 均等风险 — 每笔最大亏损固定，按止损距离反推股数
# ============================================================
class EqualRiskSizer(BaseSizer):
    """
    均等风险仓位：
      每笔最大亏损 = cash * risk_pct
      每股最大亏损 = price * stop_pct
      股数 = 每笔最大亏损 / 每股最大亏损
    """

    def __init__(self, risk_pct=0.02, stop_pct=0.05):
        self.risk_pct = risk_pct
        self.stop_pct = stop_pct

    def calc_size(self, cash, price, **kwargs):
        risk_pct = kwargs.get('risk_pct', self.risk_pct)
        stop_pct = kwargs.get('stop_pct', self.stop_pct)
        max_loss = cash * risk_pct
        loss_per_share = price * stop_pct
        if loss_per_share <= 0:
            return 0
        return max_loss / loss_per_share


# ============================================================
#  注册表
# ============================================================
SIZER_REGISTRY = {
    "固定比例": {
        "class": FixedFractionSizer,
        "params": {"fraction": (0.1, 1.0, 0.95)},
        "param_labels": {"fraction": "仓位比例"},
        "desc": "每次用可用现金的固定百分比买入，默认 95%"
    },
    "凯利公式": {
        "class": KellySizer,
        "params": {
            "win_rate": (0.1, 0.9, 0.5),
            "avg_win": (0.01, 0.10, 0.03),
            "avg_loss": (0.01, 0.10, 0.02),
        },
        "param_labels": {
            "win_rate": "预估胜率",
            "avg_win": "平均盈利（%）",
            "avg_loss": "平均亏损（%）",
        },
        "flags": {"half_kelly": "半凯利（减半）"},
        "desc": "凯利公式 f=(p*b-q)/b，根据胜率和盈亏比计算最优比例"
    },
    "ATR 波动率": {
        "class": ATRSizer,
        "params": {
            "risk_pct": (0.005, 0.05, 0.02),
            "atr_multiplier": (1.0, 5.0, 2.0),
        },
        "param_labels": {
            "risk_pct": "单笔风险（%）",
            "atr_multiplier": "ATR 倍数",
        },
        "desc": "波动越大仓位越小，size=cash×risk/(n×ATR)"
    },
    "均等风险": {
        "class": EqualRiskSizer,
        "params": {
            "risk_pct": (0.005, 0.05, 0.02),
            "stop_pct": (0.01, 0.10, 0.05),
        },
        "param_labels": {
            "risk_pct": "单笔风险（%）",
            "stop_pct": "止损距离（%）",
        },
        "desc": "每笔最大亏损固定，由止损距离反推股数"
    },
}

# ============================================================
# 情绪仓位叠加层 (Sentiment Overlay)
# ============================================================

def get_sentiment_multiplier(score):
    """根据情绪分数返回 (乘数, 标签, 说明)。
    
    情绪分数范围：正=利好, 负=利空, 绝对值越大越极端
    """
    if score > 2:
        return 1.2, "利好加仓", "情绪强烈利好，仓位加至120%"
    elif score > 0.5:
        return 1.0, "偏多正常", "偏多情绪，维持正常仓位"
    elif score > -0.5:
        return 0.8, "中性收缩", "情绪中性偏谨慎，仓位收至80%"
    elif score > -2:
        return 0.5, "偏空减半", "偏空情绪，仓位减至50%"
    elif score > -3:
        return 0.2, "利空轻仓", "利空情绪，仓位缩至20%"
    else:
        return 0.0, "强利空停仓", "强烈利空，暂停新开仓"


class SentimentPositionSizer(BaseSizer):
    """仓位叠加层：包装基础 Sizer，根据情绪缩放最终股数。
    
    策略通过 calc_size 获取的下单量 = base_sizer.calc_size() × 情绪乘数。
    每次 calc_size 调用后记录 _last_base_size / _last_multiplier / _last_label，
    供 notify_trade 读取后写入交易日志。
    """

    def __init__(self, base_sizer, sentiment_events=None):
        self.base_sizer = base_sizer
        self.sentiment_events = sentiment_events or []
        self._current_score = 0.0
        self._current_tag = ""
        self._current_news = []
        self._current_multiplier = 1.0
        self._current_label = ""
        self._current_desc = ""
        # 上一次 calc_size 的结果快照（notify_trade 读取后自行重置）
        self._last_base_size = 0
        self._last_multiplier = 1.0
        self._last_label = ""
        self._last_desc = ""

    def set_sentiment(self, score, tag, news):
        """每根 bar 调用，更新当前情绪状态。"""
        self._current_score = score
        self._current_tag = tag
        self._current_news = news
        self._current_multiplier, self._current_label, self._current_desc = \
            get_sentiment_multiplier(score)

    def calc_size(self, cash, price, **kwargs):
        """计算情绪调整后的股数。先调用基础 Sizer，再乘情绪乘数。"""
        base_size = self.base_sizer.calc_size(cash, price, **kwargs)
        adjusted = int(max(0, base_size * self._current_multiplier))
        # 记录快照供 notify_trade 读取
        self._last_base_size = int(base_size)
        self._last_multiplier = self._current_multiplier
        self._last_label = self._current_label
        self._last_desc = self._current_desc
        return adjusted