"""内存仓储（原型用，生产替换为 docs/01 的数据库实现）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import (
    AuditEntry,
    CreditProfile,
    CustomerRelation,
    Deal,
    Demand,
    Enterprise,
    Listing,
    Merchant,
)


class Store:
    def __init__(self) -> None:
        self.enterprises: dict[int, Enterprise] = {}
        self.merchants: dict[int, Merchant] = {}
        self.listings: dict[int, Listing] = {}
        self.demands: dict[int, Demand] = {}
        self.relations: dict[int, CustomerRelation] = {}
        self.credit: dict[int, CreditProfile] = {}
        self.deals: list[Deal] = []
        self.audit: list[AuditEntry] = []
        self._seq = 0

    def next_id(self) -> int:
        self._seq += 1
        return self._seq

    def add_enterprise(self, e: Enterprise) -> Enterprise:
        self.enterprises[e.enterprise_id] = e
        return e

    def add_merchant(self, m: Merchant) -> Merchant:
        self.merchants[m.merchant_id] = m
        return m

    def add_listing(self, listing: Listing) -> Listing:
        self.listings[listing.listing_id] = listing
        return listing

    def add_demand(self, d: Demand) -> Demand:
        self.demands[d.demand_id] = d
        return d

    def add_relation(self, r: CustomerRelation) -> CustomerRelation:
        self.relations[r.relation_id] = r
        return r

    def add_credit(self, c: CreditProfile) -> CreditProfile:
        self.credit[c.enterprise_id] = c
        return c

    def relations_for_customer(self, customer_id: int) -> list[CustomerRelation]:
        return [r for r in self.relations.values() if r.customer_enterprise_id == customer_id]

    def relation_of(self, merchant_id: int, customer_id: int) -> Optional[CustomerRelation]:
        for r in self.relations.values():
            if r.merchant_id == merchant_id and r.customer_enterprise_id == customer_id:
                return r
        return None

    def relations_of_merchant(self, merchant_id: int) -> list[CustomerRelation]:
        return [r for r in self.relations.values() if r.merchant_id == merchant_id]

    def last_order_at(self, buyer_id: int) -> Optional[datetime]:
        ds = [d.created_at for d in self.deals if d.buyer_enterprise_id == buyer_id]
        return max(ds) if ds else None

    def log_audit(self, entry: AuditEntry) -> None:
        self.audit.append(entry)
