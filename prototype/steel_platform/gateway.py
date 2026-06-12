"""权限/归属网关：可见性过滤 + 访问审计（对应 docs/06）。

所有数据访问都应穿过本网关。这是"绝不撬客"在架构上的物理闸门：
撮合服务只能拿到 PUBLIC 数据，私域/战略客户对第三方完全不可见。
"""
from __future__ import annotations

from datetime import datetime

from .models import AuditEntry, CustomerRelation, Listing, Visibility
from .store import Store


class PermissionGateway:
    def __init__(self, store: Store) -> None:
        self.store = store

    @staticmethod
    def _listing_visible(listing: Listing, merchant_id: int) -> bool:
        if listing.merchant_id == merchant_id:
            return True
        if listing.visibility == Visibility.PUBLIC:
            return True
        if listing.visibility == Visibility.ASSIGNED and merchant_id in listing.assigned_to:
            return True
        return False

    def visible_listings(self, merchant_id: int) -> list[Listing]:
        return [l for l in self.store.listings.values() if self._listing_visible(l, merchant_id)]

    def public_listings(self) -> list[Listing]:
        """撮合服务专用：只返回公域货源。"""
        return [
            l
            for l in self.store.listings.values()
            if l.visibility == Visibility.PUBLIC and l.status == "on_sale"
        ]

    def can_access_customer(
        self, actor_merchant_id: int, customer_id: int, now: datetime, action: str = "view"
    ) -> bool:
        """判定某商家能否访问某客户，并写审计日志。"""
        rels = self.store.relations_for_customer(customer_id)
        owned_by_actor = any(r.merchant_id == actor_merchant_id for r in rels)
        # 任何人对自己归属的客户都可访问
        if owned_by_actor:
            return self._audit(actor_merchant_id, customer_id, action, True, "owner", now)
        # 被他人设为战略/私域客户 -> 拒绝
        for r in rels:
            if r.is_strategic or r.visibility == Visibility.PRIVATE:
                return self._audit(
                    actor_merchant_id, customer_id, action, False, "owned_by_other", now
                )
        # 无任何私域归属（公域）-> 允许访问公域信息
        if not rels:
            return self._audit(actor_merchant_id, customer_id, action, True, "public", now)
        # 存在 assigned/public 关系
        for r in rels:
            if r.visibility == Visibility.PUBLIC:
                return self._audit(actor_merchant_id, customer_id, action, True, "public_rel", now)
            if r.visibility == Visibility.ASSIGNED and actor_merchant_id in r.assigned_to:
                return self._audit(actor_merchant_id, customer_id, action, True, "assigned", now)
        return self._audit(actor_merchant_id, customer_id, action, False, "owned_by_other", now)

    def _audit(
        self,
        actor: int,
        customer: int,
        action: str,
        allowed: bool,
        reason: str,
        now: datetime,
    ) -> bool:
        self.store.log_audit(
            AuditEntry(
                actor_merchant_id=actor,
                target_customer_id=customer,
                action=action,
                result="allowed" if allowed else "denied",
                reason=reason,
                occurred_at=now,
            )
        )
        return allowed

    def access_log_for_customer(self, customer_id: int) -> list[AuditEntry]:
        """商家透明看板：我的客户被谁访问过。"""
        return [a for a in self.store.audit if a.target_customer_id == customer_id]
