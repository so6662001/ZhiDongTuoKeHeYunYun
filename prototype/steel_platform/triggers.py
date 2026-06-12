"""触发器引擎：智能补货提醒 / 价格异动触达（对应 docs/04）。

铁律：scope=owner_only —— 运营触达只作用于商家自己的归属客户。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .models import RelationStatus
from .ownership import OwnershipEngine
from .store import Store


@dataclass
class Notification:
    merchant_id: int
    customer_enterprise_id: int
    trigger: str
    channel: str
    message: str


class TriggerEngine:
    def __init__(self, store: Store, ownership: OwnershipEngine) -> None:
        self.store = store
        self.ownership = ownership

    def restock_reminders(
        self, merchant_id: int, now: datetime, repurchase_cycle_days: int = 18
    ) -> list[Notification]:
        """对该商家的归属客户，若超过复购周期*1.2 仍无新单则提醒。"""
        out: list[Notification] = []
        for rel in self.store.relations_of_merchant(merchant_id):
            if rel.status == RelationStatus.RETURNED_TO_POOL:
                continue  # 已回公域，不再属于该商家
            last = self.store.last_order_at(rel.customer_enterprise_id)
            if last is None:
                continue
            threshold = timedelta(days=repurchase_cycle_days * 1.2)
            if now - last > threshold:
                ent = self.store.enterprises.get(rel.customer_enterprise_id)
                cat = ent.main_categories[0] if ent and ent.main_categories else "常采品种"
                out.append(
                    Notification(
                        merchant_id=merchant_id,
                        customer_enterprise_id=rel.customer_enterprise_id,
                        trigger="restock_reminder",
                        channel="wechat",
                        message=f"您常采的{cat}今日到货，价格可谈，已 {(now - last).days} 天未采购。",
                    )
                )
        return out

    def price_anomaly_reminders(
        self,
        merchant_id: int,
        category: str,
        change_per_ton: float,
        now: datetime,
        threshold: float = 50.0,
    ) -> list[Notification]:
        """品种价格日变动超阈值时，对关注该品种的归属客户触达。"""
        if abs(change_per_ton) < threshold:
            return []
        out: list[Notification] = []
        direction = "下跌" if change_per_ton < 0 else "上涨"
        for rel in self.store.relations_of_merchant(merchant_id):
            if rel.status == RelationStatus.RETURNED_TO_POOL:
                continue
            ent = self.store.enterprises.get(rel.customer_enterprise_id)
            if ent and category in ent.main_categories:
                out.append(
                    Notification(
                        merchant_id=merchant_id,
                        customer_enterprise_id=rel.customer_enterprise_id,
                        trigger="price_anomaly",
                        channel="sms",
                        message=f"{category}今日{direction} {abs(change_per_ton):.0f} 元/吨，"
                        f"{'低点提示，建议锁价' if change_per_ton < 0 else '注意成本变化'}。",
                    )
                )
        return out
