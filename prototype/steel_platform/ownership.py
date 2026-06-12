"""归属引擎：归属判定、保护期续期、状态流转、撞单仲裁（对应 docs/02）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from . import value as value_model
from .models import CustomerRelation, RelationStatus, RelationType, Visibility
from .store import Store

# 各归属来源的基础保护期（天），可配置（docs/02 第 2 节）
BASE_PROTECT_DAYS: dict[RelationType, int] = {
    RelationType.IMPORTED: 30,
    RelationType.INVITED: 60,
    RelationType.INQUIRED: 60,
    RelationType.DEALT: 90,
    RelationType.CLAIMED: 60,
}

# 掉保宽限期（active 到期后仍属私域的缓冲期）
GRACE_DAYS = 30

# 撞单仲裁中关系类型的优先级（数值越大越优先）
RELATION_RANK: dict[RelationType, int] = {
    RelationType.DEALT: 4,
    RelationType.INQUIRED: 3,
    RelationType.INVITED: 2,
    RelationType.IMPORTED: 2,
    RelationType.CLAIMED: 2,
}

# 反囤积治理参数（docs/02 第 11 节）
STRATEGIC_REVIEW_DAYS = 180           # 战略客户超此天数无真实互动 -> 进入"待复核/告警"
STRATEGIC_GRACE_DAYS = 365            # 战略客户超此天数无真实互动 -> 降级为普通保护（非直接入公海）
STRATEGIC_VALUE_FLOOR = 40.0          # 战略客户价值准入门槛（0-100）


class StrategicConflict(Exception):
    """同一客户已被其他商家设为战略客户。"""


class QuotaExceeded(Exception):
    """战略容量已满，不能把更多客户圈为战略（反囤积）。"""


class NotEligibleStrategic(Exception):
    """客户价值未达战略准入门槛（价值导向，而非随意圈地）。"""


class OwnershipEngine:
    def __init__(self, store: Store, value_gate: bool = False,
                 value_floor: float = STRATEGIC_VALUE_FLOOR) -> None:
        self.store = store
        self.value_gate = value_gate          # 冷启动可关闭，数据充足后开启（先规则后模型）
        self.value_floor = value_floor
        self._quota_override: dict[int, int] = {}

    # ---------------- 战略容量（动态，按价值与规模）----------------
    def set_strategic_quota(self, merchant_id: int, quota: int) -> None:
        """显式覆盖容量（如按付费档封顶）；不设则用动态容量。"""
        self._quota_override[merchant_id] = quota

    def strategic_capacity(self, merchant_id: int) -> int:
        if merchant_id in self._quota_override:
            return self._quota_override[merchant_id]
        return value_model.dynamic_capacity(self.store, merchant_id)

    # 兼容旧命名
    def strategic_quota(self, merchant_id: int) -> int:
        return self.strategic_capacity(merchant_id)

    def strategic_used(self, merchant_id: int) -> int:
        return sum(
            1 for r in self.store.relations_of_merchant(merchant_id)
            if r.is_strategic and r.status != RelationStatus.RETURNED_TO_POOL
        )

    def customer_value(self, merchant_id: int, customer_id: int, now: datetime) -> float:
        return value_model.customer_value_score(self.store, merchant_id, customer_id, now)

    def strategic_eligibility(self, merchant_id: int, customer_id: int, now: datetime) -> dict:
        """战略客户资格评估：价值准入 + 动态容量。返回结构化结果。"""
        already = False
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is not None and rel.is_strategic:
            already = True
        score = self.customer_value(merchant_id, customer_id, now)
        used = self.strategic_used(merchant_id)
        cap = self.strategic_capacity(merchant_id)
        reasons = []
        ok = True
        if self.value_gate and not already and score < self.value_floor:
            ok = False
            reasons.append(f"价值分 {score} < 准入门槛 {self.value_floor}")
        if not already and used >= cap:
            ok = False
            reasons.append(f"战略容量已满 {used}/{cap}")
        return {"ok": ok, "value_score": score, "used": used, "capacity": cap,
                "already": already, "reason": "；".join(reasons) or "符合战略客户标准"}

    def establish(
        self,
        merchant_id: int,
        customer_id: int,
        relation_type: RelationType,
        now: datetime,
    ) -> CustomerRelation:
        """建立或激活归属关系，并起算保护期。"""
        rel = self.store.relation_of(merchant_id, customer_id)
        protect_until = now + timedelta(days=BASE_PROTECT_DAYS[relation_type])
        if rel is None:
            rel = CustomerRelation(
                relation_id=self.store.next_id(),
                merchant_id=merchant_id,
                customer_enterprise_id=customer_id,
                relation_type=relation_type,
                created_at=now,
                protect_until=protect_until,
                visibility=Visibility.PRIVATE,
                status=RelationStatus.ACTIVE,
                last_interaction_at=now,
            )
            self.store.add_relation(rel)
        else:
            # 升级到更强的关系类型，并顺延保护期
            if RELATION_RANK[relation_type] >= RELATION_RANK[rel.relation_type]:
                rel.relation_type = relation_type
            rel.protect_until = max(rel.protect_until or now, protect_until)
            rel.status = RelationStatus.ACTIVE
            rel.last_interaction_at = now
        return rel

    def register_interaction(
        self, merchant_id: int, customer_id: int, now: datetime, two_way: bool = True
    ) -> Optional[CustomerRelation]:
        """有效互动触发自动续期；单方群发(two_way=False)不续期。

        对战略客户：有效互动刷新"经营时钟"(last_interaction_at)，从而维持战略身份。
        """
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is None or not two_way:
            return rel
        rel.last_interaction_at = now
        if rel.is_strategic:
            return rel  # 战略客户无固定保护期，仅靠经营时钟维持
        renewed = now + timedelta(days=BASE_PROTECT_DAYS[rel.relation_type])
        rel.protect_until = max(rel.protect_until or now, renewed)
        if rel.status == RelationStatus.EXPIRED:
            rel.status = RelationStatus.ACTIVE
        return rel

    def mark_strategic(self, merchant_id: int, customer_id: int, now: datetime) -> CustomerRelation:
        """标记战略客户：价值准入 + 动态容量 + 强制 private。全局互斥。"""
        for other in self.store.relations_for_customer(customer_id):
            if other.is_strategic and other.merchant_id != merchant_id:
                raise StrategicConflict(
                    f"客户 {customer_id} 已被商家 {other.merchant_id} 设为战略客户"
                )
        elig = self.strategic_eligibility(merchant_id, customer_id, now)
        if not elig["already"]:
            if self.value_gate and elig["value_score"] < self.value_floor:
                raise NotEligibleStrategic(
                    f"客户 {customer_id} 价值分 {elig['value_score']} 未达战略准入门槛 {self.value_floor}"
                )
            if elig["used"] >= elig["capacity"]:
                raise QuotaExceeded(
                    f"商家 {merchant_id} 战略容量已满（{elig['used']}/{elig['capacity']}），"
                    f"请释放低价值名额或随规模/付费档提升容量"
                )
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is None:
            rel = self.establish(merchant_id, customer_id, RelationType.CLAIMED, now)
        rel.is_strategic = True
        rel.visibility = Visibility.PRIVATE
        rel.status = RelationStatus.ACTIVE
        rel.protect_until = None  # 无固定保护期，靠经营时钟维持
        rel.strategic_since = now
        if rel.last_interaction_at is None:
            rel.last_interaction_at = now
        return rel

    def unmark_strategic(self, merchant_id: int, customer_id: int, now: datetime) -> Optional[CustomerRelation]:
        """商家主动释放战略名额，降级为普通保护客户（不进公海）。"""
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is None or not rel.is_strategic:
            return rel
        self._demote_strategic(rel, now)
        return rel

    def customer_opt_out(self, merchant_id: int, customer_id: int, now: datetime) -> Optional[CustomerRelation]:
        """客户制衡：客户主动解除与某商家的绑定关系 -> 直接回公海。

        客户不是商品。这是防止"圈而不耕"的最终制衡：关系需双方认可。
        """
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is None:
            return None
        rel.is_strategic = False
        rel.strategic_since = None
        rel.status = RelationStatus.RETURNED_TO_POOL
        rel.visibility = Visibility.PUBLIC
        return rel

    def strategic_health(self, rel: CustomerRelation, now: datetime) -> str:
        """战略客户健康度：healthy / at_risk(待复核) / demotable(应降级)。"""
        if not rel.is_strategic:
            return "n/a"
        last = rel.last_interaction_at or rel.strategic_since or rel.created_at
        idle = (now - last).days
        if idle > STRATEGIC_GRACE_DAYS:
            return "demotable"
        if idle > STRATEGIC_REVIEW_DAYS:
            return "at_risk"
        return "healthy"

    def _demote_strategic(self, rel: CustomerRelation, now: datetime) -> None:
        """战略降级为普通保护客户：仍属私域，给一个普通保护期，不直接入公海。"""
        rel.is_strategic = False
        rel.strategic_since = None
        rel.visibility = Visibility.PRIVATE
        rel.status = RelationStatus.ACTIVE
        rel.protect_until = now + timedelta(days=BASE_PROTECT_DAYS[rel.relation_type])

    def refresh_states(self, now: datetime) -> None:
        """定时扫描：
        - 普通客户：active -> expired -> returned_to_pool。
        - 战略客户：长期不经营(超超长宽限)则降级为普通保护(非直接入公海)，再走普通规则。
        """
        for rel in self.store.relations.values():
            if rel.is_strategic:
                # 反"圈而不耕"：战略身份需持续经营维持；超超长宽限无互动 -> 降级
                if self.strategic_health(rel, now) == "demotable":
                    self._demote_strategic(rel, now)
                continue
            if rel.protect_until is None:
                continue
            if rel.status == RelationStatus.ACTIVE and now > rel.protect_until:
                rel.status = RelationStatus.EXPIRED
            elif rel.status == RelationStatus.EXPIRED and now > rel.protect_until + timedelta(
                days=GRACE_DAYS
            ):
                rel.status = RelationStatus.RETURNED_TO_POOL
                rel.visibility = Visibility.PUBLIC

    def at_risk_strategic(self, merchant_id: int, now: datetime) -> list[CustomerRelation]:
        """供看板提醒：该商家名下"待复核/应降级"的战略客户。"""
        return [
            r for r in self.store.relations_of_merchant(merchant_id)
            if r.is_strategic and self.strategic_health(r, now) in ("at_risk", "demotable")
        ]

    def arbitrate(self, customer_id: int) -> Optional[CustomerRelation]:
        """撞单仲裁：返回该客户当前的归属商家关系；无私域归属返回 None（可进公域）。

        优先级链（docs/02 第 5 节）：
        战略 > (active>expired) > 关系类型秩 > 建立时间早者
        returned_to_pool 视为无归属。
        """
        candidates = [
            r
            for r in self.store.relations_for_customer(customer_id)
            if r.status != RelationStatus.RETURNED_TO_POOL
        ]
        if not candidates:
            return None

        def sort_key(r: CustomerRelation):
            status_rank = 1 if r.status == RelationStatus.ACTIVE else 0
            return (
                1 if r.is_strategic else 0,
                status_rank,
                RELATION_RANK[r.relation_type],
                -r.created_at.timestamp(),  # 早者优先
            )

        return max(candidates, key=sort_key)

    def is_owned(self, customer_id: int) -> bool:
        """是否存在私域归属（决定其需求能否被平台主动 push 撮合）。"""
        return self.arbitrate(customer_id) is not None

    def active_owner_merchant(self, customer_id: int) -> Optional[int]:
        """该客户当前归属商家（用于买方主动公开寻源时授予老关系优先响应权）。"""
        rel = self.arbitrate(customer_id)
        return rel.merchant_id if rel else None
