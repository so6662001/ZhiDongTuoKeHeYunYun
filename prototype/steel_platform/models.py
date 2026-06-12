"""领域模型与枚举（对应 docs/01）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class EntType(str, Enum):
    PRODUCER = "producer"
    WHOLESALER = "wholesaler"
    TRADER = "trader"
    RETAILER = "retailer"
    END_USER = "end_user"


class Visibility(str, Enum):
    PRIVATE = "private"
    ASSIGNED = "assigned"
    PUBLIC = "public"


class RelationType(str, Enum):
    IMPORTED = "imported"
    INVITED = "invited"
    INQUIRED = "inquired"
    DEALT = "dealt"
    CLAIMED = "claimed"


class RelationStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    RETURNED_TO_POOL = "returned_to_pool"


class Urgency(str, Enum):
    URGENT = "urgent"
    NORMAL = "normal"
    WATCHING = "watching"


@dataclass
class Enterprise:
    enterprise_id: int
    name: str
    ent_type: EntType
    region_code: str
    main_categories: list[str] = field(default_factory=list)
    scale: str = "small"
    credit_score: int = 60


@dataclass
class Merchant:
    merchant_id: int
    enterprise_id: int
    tier: str = "standard"


@dataclass
class Listing:
    listing_id: int
    merchant_id: int
    category: str
    spec: str
    quantity: float
    price: float
    warehouse_region: str
    price_type: str = "negotiable"
    account_period_days: int = 0
    visibility: Visibility = Visibility.PUBLIC
    status: str = "on_sale"
    inventory_age_days: int = 0
    assigned_to: list[int] = field(default_factory=list)


@dataclass
class Demand:
    demand_id: int
    enterprise_id: int
    category: str
    spec: str
    quantity: float
    delivery_region: str
    target_price: Optional[float] = None
    urgency: Urgency = Urgency.NORMAL
    is_public: bool = False
    valid_until: Optional[datetime] = None


@dataclass
class CustomerRelation:
    relation_id: int
    merchant_id: int
    customer_enterprise_id: int
    relation_type: RelationType
    created_at: datetime
    protect_until: Optional[datetime] = None
    is_strategic: bool = False
    visibility: Visibility = Visibility.PRIVATE
    status: RelationStatus = RelationStatus.ACTIVE
    assigned_to: list[int] = field(default_factory=list)


@dataclass
class CreditProfile:
    enterprise_id: int
    repayment_on_time: float = 1.0
    overdue_count: int = 0
    fulfillment_rate: float = 1.0
    cancel_rate: float = 0.0
    years_in_business: int = 1
    score: int = 60
    tier: str = "B"


@dataclass
class Deal:
    deal_id: int
    buyer_enterprise_id: int
    seller_merchant_id: int
    category: str
    spec: str
    quantity: float
    price: float
    created_at: datetime
    account_period_days: int = 0
    repaid: bool = False


@dataclass
class AuditEntry:
    actor_merchant_id: Optional[int]
    target_customer_id: Optional[int]
    action: str
    result: str
    reason: str
    occurred_at: datetime
    channel: str = "api"
