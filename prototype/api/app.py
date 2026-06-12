"""FastAPI 应用：把核心引擎封装为 REST API（方向1）。

运行：uvicorn api.app:app --reload  （在 prototype 目录下）
文档：访问 /docs (Swagger) 或 /redoc。

所有客户数据访问都经过权限/归属网关——防撬客在 API 层同样生效。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steel_platform.credit import recommend_terms, score_credit
from steel_platform.gateway import PermissionGateway
from steel_platform.matching import MatchingEngine
from steel_platform.models import (
    CreditProfile,
    Demand,
    Enterprise,
    EntType,
    Listing,
    Merchant,
    RelationType,
    Urgency,
    Visibility,
)
from steel_platform.ownership import OwnershipEngine, StrategicConflict
from steel_platform.pricelock import PriceLockEngine
from steel_platform.recovery import AbandonContext, RecoveryEngine
from steel_platform.store import Store
from steel_platform.triggers import TriggerEngine

from .schemas import (
    CreditIn,
    DemandIn,
    EnterpriseIn,
    ListingIn,
    MatchOut,
    MerchantIn,
    PriceLockIn,
    RecoveryIn,
    RelationIn,
)


class AppState:
    def __init__(self) -> None:
        self.store = Store()
        self.own = OwnershipEngine(self.store)
        self.gw = PermissionGateway(self.store)
        self.match = MatchingEngine(self.store, self.own, self.gw)
        self.trig = TriggerEngine(self.store, self.own)
        self.lock = PriceLockEngine()
        self.recovery = RecoveryEngine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="货袋子钢铁现货平台 · 智能获客/运营/转化 API",
        description="核心引擎参考实现的 REST 接口。防撬客铁律在 API 层同样生效。",
        version="0.1.0",
    )
    state = AppState()
    app.state.engine = state

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/enterprises", status_code=201)
    def add_enterprise(body: EnterpriseIn):
        state.store.add_enterprise(
            Enterprise(
                enterprise_id=body.enterprise_id,
                name=body.name,
                ent_type=EntType(body.ent_type),
                region_code=body.region_code,
                main_categories=body.main_categories,
                scale=body.scale,
                credit_score=body.credit_score,
            )
        )
        return {"enterprise_id": body.enterprise_id}

    @app.post("/merchants", status_code=201)
    def add_merchant(body: MerchantIn):
        state.store.add_merchant(Merchant(body.merchant_id, body.enterprise_id, body.tier))
        return {"merchant_id": body.merchant_id}

    @app.post("/relations", status_code=201)
    def establish_relation(body: RelationIn):
        rel = state.own.establish(
            body.merchant_id,
            body.customer_enterprise_id,
            RelationType(body.relation_type),
            datetime.now(),
        )
        return {"relation_id": rel.relation_id, "status": rel.status.value}

    @app.post("/relations/strategic", status_code=201)
    def mark_strategic(body: RelationIn):
        try:
            rel = state.own.mark_strategic(
                body.merchant_id, body.customer_enterprise_id, datetime.now()
            )
        except StrategicConflict as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"relation_id": rel.relation_id, "is_strategic": rel.is_strategic}

    @app.get("/relations/arbitrate/{customer_id}")
    def arbitrate(customer_id: int):
        rel = state.own.arbitrate(customer_id)
        return {
            "customer_id": customer_id,
            "owned": rel is not None,
            "owner_merchant_id": rel.merchant_id if rel else None,
        }

    @app.get("/gateway/access")
    def check_access(actor_merchant_id: int, customer_id: int):
        allowed = state.gw.can_access_customer(actor_merchant_id, customer_id, datetime.now())
        return {"actor_merchant_id": actor_merchant_id, "customer_id": customer_id,
                "allowed": allowed}

    @app.get("/audit/{customer_id}")
    def audit(customer_id: int):
        return [
            {"actor_merchant_id": a.actor_merchant_id, "action": a.action,
             "result": a.result, "reason": a.reason}
            for a in state.gw.access_log_for_customer(customer_id)
        ]

    @app.post("/listings", status_code=201)
    def add_listing(body: ListingIn):
        state.store.add_listing(
            Listing(
                listing_id=body.listing_id,
                merchant_id=body.merchant_id,
                category=body.category,
                spec=body.spec,
                quantity=body.quantity,
                price=body.price,
                warehouse_region=body.warehouse_region,
                account_period_days=body.account_period_days,
                visibility=Visibility(body.visibility),
                inventory_age_days=body.inventory_age_days,
            )
        )
        return {"listing_id": body.listing_id}

    @app.post("/demands", status_code=201)
    def add_demand(body: DemandIn):
        state.store.add_demand(
            Demand(
                demand_id=body.demand_id,
                enterprise_id=body.enterprise_id,
                category=body.category,
                spec=body.spec,
                quantity=body.quantity,
                delivery_region=body.delivery_region,
                target_price=body.target_price,
                urgency=Urgency(body.urgency),
                is_public=body.is_public,
            )
        )
        return {"demand_id": body.demand_id}

    @app.post("/match/listing/{listing_id}", response_model=list[MatchOut])
    def match_listing(listing_id: int, top_n: int = 5):
        listing = state.store.listings.get(listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        results = state.match.match_for_listing(listing, top_n=top_n)
        return [
            MatchOut(
                demand_id=r.demand.demand_id,
                listing_id=listing_id,
                buyer_enterprise_id=r.demand.enterprise_id,
                score=r.score,
                rationale=r.rationale,
            )
            for r in results
        ]

    @app.post("/match/demand/{demand_id}", response_model=list[MatchOut])
    def match_demand(demand_id: int, top_n: int = 5):
        demand = state.store.demands.get(demand_id)
        if demand is None:
            raise HTTPException(404, "demand not found")
        results = state.match.match_for_demand(demand, top_n=top_n)
        return [
            MatchOut(
                demand_id=demand_id,
                listing_id=r.listing.listing_id,
                buyer_enterprise_id=demand.enterprise_id,
                score=r.score,
                rationale=r.rationale,
            )
            for r in results
        ]

    @app.post("/credit/terms")
    def credit_terms(body: CreditIn):
        cp = CreditProfile(
            enterprise_id=body.enterprise_id,
            repayment_on_time=body.repayment_on_time,
            overdue_count=body.overdue_count,
            fulfillment_rate=body.fulfillment_rate,
            cancel_rate=body.cancel_rate,
            years_in_business=body.years_in_business,
        )
        score, tier = score_credit(cp)
        rec = recommend_terms(cp, body.order_amount)
        return {
            "score": score,
            "tier": tier,
            "account_period_days": rec.account_period_days,
            "credit_limit": rec.credit_limit,
            "require_prepay_ratio": rec.require_prepay_ratio,
            "rationale": rec.rationale,
        }

    @app.post("/triggers/restock")
    def restock(merchant_id: int, repurchase_cycle_days: int = 18):
        # 演示用：以当前时间向后偏移触发判断
        notes = state.trig.restock_reminders(
            merchant_id, datetime.now(), repurchase_cycle_days
        )
        return [
            {"customer_enterprise_id": n.customer_enterprise_id, "channel": n.channel,
             "message": n.message}
            for n in notes
        ]

    @app.post("/pricelock")
    def create_lock(body: PriceLockIn):
        now = datetime.now()
        r = state.lock.create_lock(
            body.buyer_enterprise_id, body.listing_id, body.price, body.quantity,
            body.duration_hours, now, body.volatility,
        )
        if not r.ok:
            raise HTTPException(400, r.reason)
        return {
            "lock_id": r.lock.lock_id,
            "locked_price": r.lock.locked_price,
            "margin": r.lock.margin,
            "expires_at": r.lock.expires_at.isoformat(),
        }

    @app.post("/pricelock/{lock_id}/exercise")
    def exercise_lock(lock_id: int):
        r = state.lock.exercise(lock_id, datetime.now())
        if not r.ok:
            raise HTTPException(400, r.reason)
        return {"lock_id": lock_id, "status": r.lock.status.value}

    @app.post("/recovery/plan")
    def recovery_plan(body: RecoveryIn):
        now = datetime.now()
        ctx = AbandonContext(
            buyer_enterprise_id=body.buyer_enterprise_id,
            quoted_price=body.quoted_price,
            buyer_hist_avg_price=body.buyer_hist_avg_price,
            market_avg_price=body.market_avg_price,
            requested_longer_terms=body.requested_longer_terms,
            delivery_distance_far=body.delivery_distance_far,
            price_sensitivity=body.price_sensitivity,
            inquired_at=now - timedelta(hours=body.hours_since_inquiry),
            now=now,
        )
        plan = state.recovery.make_plan(ctx)
        if plan is None:
            return {"stuck": False}
        return {
            "stuck": True,
            "blocker": plan.blocker.value,
            "action": plan.action,
            "needs_human_confirm": plan.needs_human_confirm,
            "message": plan.message,
        }

    return app


app = create_app()
