"""归属引擎：归属判定、保护期续期、状态流转、撞单仲裁（对应 docs/02）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

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


class StrategicConflict(Exception):
    """同一客户已被其他商家设为战略客户。"""


class OwnershipEngine:
    def __init__(self, store: Store) -> None:
        self.store = store

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
            )
            self.store.add_relation(rel)
        else:
            # 升级到更强的关系类型，并顺延保护期
            if RELATION_RANK[relation_type] >= RELATION_RANK[rel.relation_type]:
                rel.relation_type = relation_type
            rel.protect_until = max(rel.protect_until or now, protect_until)
            rel.status = RelationStatus.ACTIVE
        return rel

    def register_interaction(
        self, merchant_id: int, customer_id: int, now: datetime, two_way: bool = True
    ) -> Optional[CustomerRelation]:
        """有效互动触发自动续期；单方群发(two_way=False)不续期。"""
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is None or not two_way:
            return rel
        renewed = now + timedelta(days=BASE_PROTECT_DAYS[rel.relation_type])
        rel.protect_until = max(rel.protect_until or now, renewed)
        if rel.status == RelationStatus.EXPIRED:
            rel.status = RelationStatus.ACTIVE
        return rel

    def mark_strategic(self, merchant_id: int, customer_id: int, now: datetime) -> CustomerRelation:
        """标记战略客户：永久绑定 + 强制 private。全局互斥。"""
        for other in self.store.relations_for_customer(customer_id):
            if other.is_strategic and other.merchant_id != merchant_id:
                raise StrategicConflict(
                    f"客户 {customer_id} 已被商家 {other.merchant_id} 设为战略客户"
                )
        rel = self.store.relation_of(merchant_id, customer_id)
        if rel is None:
            rel = self.establish(merchant_id, customer_id, RelationType.CLAIMED, now)
        rel.is_strategic = True
        rel.visibility = Visibility.PRIVATE
        rel.status = RelationStatus.ACTIVE
        rel.protect_until = None  # 永久
        return rel

    def refresh_states(self, now: datetime) -> None:
        """定时扫描：active->expired->returned_to_pool（战略客户跳过）。"""
        for rel in self.store.relations.values():
            if rel.is_strategic:
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
        """是否存在私域归属（决定其需求能否进公域撮合）。"""
        return self.arbitrate(customer_id) is not None
