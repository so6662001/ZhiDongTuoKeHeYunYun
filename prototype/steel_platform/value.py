"""客户价值模型与战略容量（对应 docs/02 第 11 节升级：价值准入 + 动态容量）。

战略客户资格不再靠固定数字配额，而是：
1. 价值准入门槛：客户对该商家的价值分需达标；
2. 动态容量：上限随商家规模（活跃客户数/GMV 档）自动伸缩，避免"大商家不够、小商家太多"。
"""
from __future__ import annotations

import math
from datetime import datetime

from .models import RelationStatus
from .store import Store

# 归一化上限（示意，可按行业校准）
AMOUNT_CAP = 5_000_000.0   # 近 12 月成交额上限（元）
FREQ_CAP = 24.0            # 近 12 月成交次数上限
TENURE_CAP_DAYS = 720.0    # 合作时长上限（天）
WINDOW_DAYS = 365

# 价值分权重
VALUE_WEIGHTS = {
    "amount": 0.35,    # 成交额（毛利的代理）
    "freq": 0.25,      # 复购频次
    "recency": 0.15,   # 最近活跃
    "tenure": 0.10,    # 合作时长/稳定性
    "repay": 0.15,     # 回款表现
}

# 动态容量参数
CAPACITY_RATIO = 0.10      # 战略名额 = 活跃客户数 × 10%
CAPACITY_BASE = 5          # 小商家保底名额
CAPACITY_HARD_CAP = 500    # 绝对上限


def customer_value_score(store: Store, merchant_id: int, customer_id: int,
                         now: datetime, window_days: int = WINDOW_DAYS) -> float:
    """客户对某商家的价值分（0-100）。无成交历史则偏低。"""
    deals = [
        d for d in store.deals
        if d.buyer_enterprise_id == customer_id and d.seller_merchant_id == merchant_id
        and (now - d.created_at).days <= window_days
    ]
    if deals:
        amount = sum(d.price * d.quantity for d in deals)
        freq = len(deals)
        last = max(d.created_at for d in deals)
        first = min(d.created_at for d in deals)
        recency_days = (now - last).days
        tenure_days = (now - first).days
        repaid_ratio = sum(1 for d in deals if d.repaid) / len(deals)
    else:
        amount = freq = tenure_days = 0
        recency_days = window_days
        repaid_ratio = 0.0

    cp = store.credit.get(customer_id)
    if cp is not None:
        repaid_ratio = max(repaid_ratio, cp.repayment_on_time)

    amount_n = min(1.0, amount / AMOUNT_CAP)
    freq_n = min(1.0, freq / FREQ_CAP)
    recency_n = max(0.0, 1.0 - recency_days / float(window_days))
    tenure_n = min(1.0, tenure_days / TENURE_CAP_DAYS)
    repay_n = max(0.0, min(1.0, repaid_ratio))

    score = 100.0 * (
        VALUE_WEIGHTS["amount"] * amount_n
        + VALUE_WEIGHTS["freq"] * freq_n
        + VALUE_WEIGHTS["recency"] * recency_n
        + VALUE_WEIGHTS["tenure"] * tenure_n
        + VALUE_WEIGHTS["repay"] * repay_n
    )
    return round(score, 1)


def dynamic_capacity(store: Store, merchant_id: int,
                     ratio: float = CAPACITY_RATIO, base: int = CAPACITY_BASE,
                     hard_cap: int = CAPACITY_HARD_CAP) -> int:
    """战略名额上限随商家规模自动伸缩。"""
    active = sum(
        1 for r in store.relations_of_merchant(merchant_id)
        if r.status != RelationStatus.RETURNED_TO_POOL
    )
    return int(min(hard_cap, max(base, math.ceil(active * ratio))))
