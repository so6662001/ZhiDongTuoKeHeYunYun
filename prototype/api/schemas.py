"""API 请求/响应模型（Pydantic）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class EnterpriseIn(BaseModel):
    enterprise_id: int
    name: str
    ent_type: str
    region_code: str
    main_categories: list[str] = []
    scale: str = "small"
    credit_score: int = 60


class MerchantIn(BaseModel):
    merchant_id: int
    enterprise_id: int
    tier: str = "standard"


class RelationIn(BaseModel):
    merchant_id: int
    customer_enterprise_id: int
    relation_type: str = "dealt"


class ListingIn(BaseModel):
    listing_id: int
    merchant_id: int
    category: str
    spec: str
    quantity: float
    price: float
    warehouse_region: str
    account_period_days: int = 0
    visibility: str = "public"
    inventory_age_days: int = 0


class DemandIn(BaseModel):
    demand_id: int
    enterprise_id: int
    category: str
    spec: str
    quantity: float
    delivery_region: str
    target_price: Optional[float] = None
    urgency: str = "normal"
    is_public: bool = False


class CreditIn(BaseModel):
    enterprise_id: int
    repayment_on_time: float = 1.0
    overdue_count: int = 0
    fulfillment_rate: float = 1.0
    cancel_rate: float = 0.0
    years_in_business: int = 1
    order_amount: float = 100000.0


class PriceLockIn(BaseModel):
    buyer_enterprise_id: int
    listing_id: int
    price: float
    quantity: float
    duration_hours: int = 6
    volatility: float = 0.0


class RecoveryIn(BaseModel):
    buyer_enterprise_id: int
    quoted_price: float
    market_avg_price: float
    buyer_hist_avg_price: Optional[float] = None
    requested_longer_terms: bool = False
    delivery_distance_far: bool = False
    price_sensitivity: float = 0.5
    hours_since_inquiry: float = 25.0


class MatchOut(BaseModel):
    demand_id: int
    listing_id: int
    buyer_enterprise_id: int
    score: float
    rationale: str
