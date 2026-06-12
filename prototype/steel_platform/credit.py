"""信用评分与账期推荐（对应 docs/05）。"""
from __future__ import annotations

from dataclasses import dataclass

from .models import CreditProfile


@dataclass
class TermsRecommendation:
    account_period_days: int
    credit_limit: float
    require_prepay_ratio: float
    tier: str
    rationale: str


def score_credit(cp: CreditProfile) -> tuple[int, str]:
    """根据回款、履约、取消率、经营年限计算 0-100 信用分与等级。"""
    repayment = cp.repayment_on_time  # 0-1
    fulfillment = cp.fulfillment_rate  # 0-1
    cancel_penalty = cp.cancel_rate  # 0-1
    overdue_penalty = min(1.0, cp.overdue_count / 10.0)
    tenure = min(1.0, cp.years_in_business / 10.0)

    raw = (
        0.45 * repayment
        + 0.30 * fulfillment
        + 0.25 * tenure
        - 0.15 * cancel_penalty
        - 0.20 * overdue_penalty
    )
    score = int(max(0.0, min(1.0, raw)) * 100)

    if score >= 80:
        tier = "A"
    elif score >= 65:
        tier = "B"
    elif score >= 50:
        tier = "C"
    else:
        tier = "D"
    return score, tier


def recommend_terms(cp: CreditProfile, order_amount: float) -> TermsRecommendation:
    """按信用等级推荐可安全给出的账期/额度/预付比例。"""
    score, tier = score_credit(cp)
    table = {
        "A": (30, 2.0, 0.0, "信用优良，可给较长账期与高额度"),
        "B": (15, 1.0, 0.0, "信用良好，可给短账期"),
        "C": (0, 0.3, 0.5, "信用一般，建议预付为主"),
        "D": (0, 0.0, 1.0, "信用偏弱，仅现款现货"),
    }
    days, limit_mult, prepay, why = table[tier]
    return TermsRecommendation(
        account_period_days=days,
        credit_limit=round(order_amount * limit_mult, 2),
        require_prepay_ratio=prepay,
        tier=tier,
        rationale=why,
    )
