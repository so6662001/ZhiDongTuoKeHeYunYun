"""弃单挽回引擎（对应 docs/05 第 6 节）。

对"询价后超时未成交"或"下单后未打款"的单子，AI 推断卡点（价高/账期/物流/观望），
生成针对性挽回方案；涉及让利、账期的方案需卖方/业务员确认。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class Blocker(str, Enum):
    PRICE = "price_too_high"
    TERMS = "terms_unsatisfied"
    LOGISTICS = "logistics_cost"
    WATCHING = "just_watching"


@dataclass
class AbandonContext:
    buyer_enterprise_id: int
    quoted_price: float
    buyer_hist_avg_price: Optional[float]   # 买方历史成交均价
    market_avg_price: float
    requested_longer_terms: bool            # 是否曾申请更长账期
    delivery_distance_far: bool             # 收货地是否偏远
    price_sensitivity: float                # 0-1，价格敏感度
    inquired_at: datetime
    now: datetime


@dataclass
class RecoveryPlan:
    blocker: Blocker
    action: str
    needs_human_confirm: bool
    message: str


# 询价后多久未成交视为"弃单/卡住"
STUCK_AFTER = timedelta(hours=24)


class RecoveryEngine:
    def is_stuck(self, ctx: AbandonContext) -> bool:
        return ctx.now - ctx.inquired_at >= STUCK_AFTER

    def diagnose(self, ctx: AbandonContext) -> Blocker:
        """按优先级判断主要卡点。"""
        ref = ctx.buyer_hist_avg_price or ctx.market_avg_price
        if ctx.quoted_price > ref * 1.02:
            return Blocker.PRICE
        if ctx.requested_longer_terms:
            return Blocker.TERMS
        if ctx.delivery_distance_far:
            return Blocker.LOGISTICS
        return Blocker.WATCHING

    def make_plan(self, ctx: AbandonContext) -> Optional[RecoveryPlan]:
        if not self.is_stuck(ctx):
            return None
        blocker = self.diagnose(ctx)
        if blocker == Blocker.PRICE:
            ref = ctx.buyer_hist_avg_price or ctx.market_avg_price
            gap = ctx.quoted_price - ref
            return RecoveryPlan(
                blocker=blocker,
                action="seller_discount_or_alternative",
                needs_human_confirm=True,  # 让利需卖方确认
                message=f"报价高于其参考价约 {gap:.0f} 元/吨，建议让利或推平价替代货源。",
            )
        if blocker == Blocker.TERMS:
            return RecoveryPlan(
                blocker=blocker,
                action="relax_terms_within_credit",
                needs_human_confirm=True,  # 账期需结合信用风控确认
                message="买方在意账期，建议在信用额度允许内适当放宽账期。",
            )
        if blocker == Blocker.LOGISTICS:
            return RecoveryPlan(
                blocker=blocker,
                action="offer_delivered_price_or_nearby_stock",
                needs_human_confirm=False,
                message="收货地偏远，建议提供含运报价或推荐就近货源。",
            )
        return RecoveryPlan(
            blocker=blocker,
            action="lock_price_or_low_point_alert",
            needs_human_confirm=False,
            message="买方处于观望，建议推送锁价提示/低点提醒制造下单理由。",
        )
