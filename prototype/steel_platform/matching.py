"""公域供需撮合评分引擎（对应 docs/03）。

铁律：撮合候选只来自公域。任何存在私域归属的买方需求都被排除，
绝不把私域/战略客户撮合给第三方。
"""
from __future__ import annotations

from dataclasses import dataclass

from typing import Optional

from .gateway import PermissionGateway
from .matching_utils import region_proximity, spec_compatible
from .models import Demand, Listing, Urgency
from .ownership import OwnershipEngine
from .ranking import LogisticRanker
from .store import Store

# 评分权重，可配置（docs/03 第 1.2 节）
WEIGHTS = {
    "price": 0.30,
    "region": 0.20,
    "history": 0.15,
    "credit": 0.20,
    "urgency": 0.15,
}

URGENCY_SCORE = {Urgency.URGENT: 1.0, Urgency.NORMAL: 0.6, Urgency.WATCHING: 0.3}


@dataclass
class MatchResult:
    demand: Demand
    listing: Listing
    score: float
    rationale: str


class MatchingEngine:
    def __init__(
        self,
        store: Store,
        ownership: OwnershipEngine,
        gateway: PermissionGateway,
        ranker: Optional[LogisticRanker] = None,
    ) -> None:
        self.store = store
        self.ownership = ownership
        self.gateway = gateway
        self.ranker = ranker  # 训练成熟后用模型分替代规则分

    def _price_match(self, demand: Demand, listing: Listing) -> float:
        if demand.target_price is None or listing.price <= 0:
            return 0.5
        ratio = listing.price / demand.target_price
        if ratio <= 1.0:
            return 1.0
        return max(0.0, 1.0 - (ratio - 1.0) * 5)  # 高于心理价位则快速衰减

    def _credit_score(self, buyer_id: int) -> float:
        cp = self.store.credit.get(buyer_id)
        ent = self.store.enterprises.get(buyer_id)
        raw = cp.score if cp else (ent.credit_score if ent else 60)
        return raw / 100.0

    def _history_fit(self, buyer_id: int, listing: Listing) -> float:
        hits = sum(
            1
            for d in self.store.deals
            if d.buyer_enterprise_id == buyer_id
            and d.seller_merchant_id == listing.merchant_id
            and d.category == listing.category
        )
        return min(1.0, hits / 3.0)

    def feature_vector(self, demand: Demand, listing: Listing) -> dict[str, float]:
        """统一特征向量：规则评分与排序模型同源（docs/03）。"""
        return {
            "price": self._price_match(demand, listing),
            "region": region_proximity(demand.delivery_region, listing.warehouse_region),
            "history": self._history_fit(demand.enterprise_id, listing),
            "credit": self._credit_score(demand.enterprise_id),
            "urgency": URGENCY_SCORE[demand.urgency],
        }

    def rule_score(self, features: dict[str, float]) -> float:
        return round(sum(WEIGHTS[f] * features[f] for f in WEIGHTS), 4)

    def score(self, demand: Demand, listing: Listing) -> float:
        feats = self.feature_vector(demand, listing)
        if self.ranker is not None and self.ranker.trained:
            return round(self.ranker.predict(feats), 4)
        return self.rule_score(feats)

    def _is_eligible_demand(self, demand: Demand) -> bool:
        """需求可进公域撮合的条件：买方无私域归属，或买方主动公开。"""
        if self.ownership.is_owned(demand.enterprise_id) and not demand.is_public:
            return False
        return True

    def match_for_listing(self, listing: Listing, top_n: int = 5) -> list[MatchResult]:
        """卖方挂货 -> 反向匹配公域买方需求。"""
        if listing.visibility != "public" and listing.visibility.value != "public":
            return []
        results: list[MatchResult] = []
        for demand in self.store.demands.values():
            if not spec_compatible(demand.category, demand.spec, listing.category, listing.spec):
                continue
            if listing.quantity < demand.quantity * 0.5:  # 支持部分满足/拼单下限
                continue
            if not self._is_eligible_demand(demand):
                continue  # 私域客户的需求绝不进撮合
            sc = self.score(demand, listing)
            results.append(
                MatchResult(
                    demand=demand,
                    listing=listing,
                    score=sc,
                    rationale=f"price/region/credit 综合得分 {sc}",
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n]

    def match_for_demand(self, demand: Demand, top_n: int = 5) -> list[MatchResult]:
        """买方需求 -> 正向匹配公域货源。"""
        if not self._is_eligible_demand(demand):
            return []
        results: list[MatchResult] = []
        for listing in self.gateway.public_listings():
            if not spec_compatible(demand.category, demand.spec, listing.category, listing.spec):
                continue
            if listing.quantity < demand.quantity * 0.5:
                continue
            sc = self.score(demand, listing)
            results.append(
                MatchResult(demand=demand, listing=listing, score=sc, rationale=f"得分 {sc}")
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n]
