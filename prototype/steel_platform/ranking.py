"""撮合排序模型与反馈闭环（对应 docs/03 "先规则后模型" 升级路线）。

纯标准库实现的逻辑回归 Learning-to-Rank（pointwise）：
- 特征来自撮合引擎的统一特征向量（与规则评分同源）。
- 用真实反馈(点击/询价/成交=正样本，曝光未转化=负样本)在线/批量训练。
- 训练成熟后由 MatchingEngine 用模型分替换规则分，形成闭环。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

FEATURE_NAMES = ["price", "region", "history", "credit", "urgency"]


@dataclass
class FeedbackSample:
    features: dict[str, float]
    label: int  # 1=正反馈(询价/成交) 0=负反馈(曝光未转化)


class FeedbackStore:
    """收集撮合曝光与转化反馈，供模型训练。"""

    def __init__(self) -> None:
        self.samples: list[FeedbackSample] = []

    def record(self, features: dict[str, float], label: int) -> None:
        self.samples.append(FeedbackSample(dict(features), int(label)))

    def __len__(self) -> int:
        return len(self.samples)


class LogisticRanker:
    def __init__(self, lr: float = 0.3, l2: float = 1e-4) -> None:
        self.w: dict[str, float] = {f: 0.0 for f in FEATURE_NAMES}
        self.b: float = 0.0
        self.lr = lr
        self.l2 = l2
        self.trained = False

    def _z(self, x: dict[str, float]) -> float:
        return self.b + sum(self.w[f] * x.get(f, 0.0) for f in FEATURE_NAMES)

    def predict(self, x: dict[str, float]) -> float:
        z = self._z(x)
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        ez = math.exp(z)
        return ez / (1.0 + ez)

    def train(self, store: FeedbackStore, epochs: int = 300) -> "LogisticRanker":
        if len(store) == 0:
            return self
        for _ in range(epochs):
            for s in store.samples:
                p = self.predict(s.features)
                err = p - s.label
                for f in FEATURE_NAMES:
                    grad = err * s.features.get(f, 0.0) + self.l2 * self.w[f]
                    self.w[f] -= self.lr * grad
                self.b -= self.lr * err
        self.trained = True
        return self

    def auc(self, store: FeedbackStore) -> float:
        """简单 AUC：正负样本对中模型给正样本更高分的比例。"""
        pos = [self.predict(s.features) for s in store.samples if s.label == 1]
        neg = [self.predict(s.features) for s in store.samples if s.label == 0]
        if not pos or not neg:
            return 0.5
        wins = sum(1 for p in pos for n in neg if p > n)
        ties = sum(1 for p in pos for n in neg if p == n)
        return (wins + 0.5 * ties) / (len(pos) * len(neg))
