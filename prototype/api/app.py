"""FastAPI 应用：把核心引擎封装为 REST API，带鉴权/多租户与 SQLite 持久化。

运行：cd prototype && uvicorn api.app:app --reload
文档：/docs (Swagger)；前端：/ui

安全要点：
- 涉及客户数据的接口都需 Bearer 令牌，actor = 已鉴权商家，杜绝伪造身份冲抢客户。
- 所有客户访问经过权限/归属网关——防撬客在 API 层同样生效。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
from steel_platform.ownership import (
    NotEligibleStrategic,
    OwnershipEngine,
    QuotaExceeded,
    StrategicConflict,
)
from steel_platform.persistence import connect, load_store, save_store
from steel_platform.pricelock import PriceLockEngine
from steel_platform.recovery import AbandonContext, RecoveryEngine
from steel_platform.store import Store
from steel_platform.triggers import TriggerEngine

from .auth import MerchantContext, TokenRegistry, make_auth_dependency
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

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


class AppState:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self.conn = connect(db_path) if db_path else None
        self.store = load_store(self.conn) if self.conn else Store()
        self.own = OwnershipEngine(self.store)
        self.gw = PermissionGateway(self.store)
        self.match = MatchingEngine(self.store, self.own, self.gw)
        self.trig = TriggerEngine(self.store, self.own)
        self.lock = PriceLockEngine()
        self.recovery = RecoveryEngine()
        self.tokens = TokenRegistry()

    def persist(self) -> None:
        if self.conn is not None:
            save_store(self.store, self.conn)


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(
        title="货袋子钢铁现货平台 · 智能获客/运营/转化 API",
        description="核心引擎参考实现的 REST 接口。带鉴权/多租户，防撬客在 API 层同样生效。",
        version="0.2.0",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    state = AppState(db_path)
    app.state.engine = state
    auth = make_auth_dependency(state.tokens)

    # ---------------- 公共/引导接口 ----------------
    @app.get("/health")
    def health():
        return {"status": "ok", "persistent": state.conn is not None}

    @app.post("/enterprises", status_code=201)
    def add_enterprise(body: EnterpriseIn):
        state.store.add_enterprise(Enterprise(
            enterprise_id=body.enterprise_id, name=body.name, ent_type=EntType(body.ent_type),
            region_code=body.region_code, main_categories=body.main_categories,
            scale=body.scale, credit_score=body.credit_score))
        return {"enterprise_id": body.enterprise_id}

    @app.post("/merchants", status_code=201)
    def add_merchant(body: MerchantIn):
        """创建商家并签发演示令牌（生产由鉴权中心签发）。"""
        state.store.add_merchant(Merchant(body.merchant_id, body.enterprise_id, body.tier))
        token = f"tok-{body.merchant_id}"
        state.tokens.issue(body.merchant_id, token, body.tier)
        return {"merchant_id": body.merchant_id, "token": token}

    @app.post("/listings", status_code=201)
    def add_listing(body: ListingIn, ctx: MerchantContext = Depends(auth)):
        if body.merchant_id != ctx.merchant_id:
            raise HTTPException(403, "只能为自己（已鉴权商家）创建货源")
        state.store.add_listing(Listing(
            listing_id=body.listing_id, merchant_id=body.merchant_id, category=body.category,
            spec=body.spec, quantity=body.quantity, price=body.price,
            warehouse_region=body.warehouse_region, account_period_days=body.account_period_days,
            visibility=Visibility(body.visibility), inventory_age_days=body.inventory_age_days))
        return {"listing_id": body.listing_id}

    @app.post("/demands", status_code=201)
    def add_demand(body: DemandIn):
        state.store.add_demand(Demand(
            demand_id=body.demand_id, enterprise_id=body.enterprise_id, category=body.category,
            spec=body.spec, quantity=body.quantity, delivery_region=body.delivery_region,
            target_price=body.target_price, urgency=Urgency(body.urgency), is_public=body.is_public))
        return {"demand_id": body.demand_id}

    # ---------------- 归属与防撬客（需鉴权，actor=令牌商家）----------------
    @app.post("/relations", status_code=201)
    def establish_relation(body: RelationIn, ctx: MerchantContext = Depends(auth)):
        rel = state.own.establish(
            ctx.merchant_id, body.customer_enterprise_id,
            RelationType(body.relation_type), datetime.now())
        return {"relation_id": rel.relation_id, "merchant_id": ctx.merchant_id,
                "status": rel.status.value}

    @app.post("/relations/strategic", status_code=201)
    def mark_strategic(body: RelationIn, ctx: MerchantContext = Depends(auth)):
        try:
            rel = state.own.mark_strategic(ctx.merchant_id, body.customer_enterprise_id,
                                           datetime.now())
        except StrategicConflict as e:
            raise HTTPException(status_code=409, detail=str(e))
        except (QuotaExceeded, NotEligibleStrategic) as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"relation_id": rel.relation_id, "is_strategic": rel.is_strategic,
                "strategic_used": state.own.strategic_used(ctx.merchant_id),
                "strategic_capacity": state.own.strategic_capacity(ctx.merchant_id)}

    @app.get("/strategic/eligibility/{customer_id}")
    def strategic_eligibility(customer_id: int, ctx: MerchantContext = Depends(auth)):
        return state.own.strategic_eligibility(ctx.merchant_id, customer_id, datetime.now())

    @app.post("/relations/customer-opt-out")
    def customer_opt_out(body: RelationIn, merchant_id: int, ctx: MerchantContext = Depends(auth)):
        """客户侧主动解除与某商家的绑定（买方主权/反囤积兜底）。"""
        rel = state.own.customer_opt_out(merchant_id, body.customer_enterprise_id, datetime.now())
        if rel is None:
            raise HTTPException(404, "关系不存在")
        return {"customer_id": body.customer_enterprise_id, "released_from": merchant_id,
                "status": rel.status.value}

    @app.delete("/relations/strategic/{customer_id}")
    def unmark_strategic(customer_id: int, ctx: MerchantContext = Depends(auth)):
        rel = state.own.unmark_strategic(ctx.merchant_id, customer_id, datetime.now())
        if rel is None:
            raise HTTPException(404, "关系不存在")
        return {"customer_id": customer_id, "is_strategic": rel.is_strategic}

    @app.get("/strategic/quota")
    def strategic_quota(ctx: MerchantContext = Depends(auth)):
        now = datetime.now()
        at_risk = state.own.at_risk_strategic(ctx.merchant_id, now)
        return {"used": state.own.strategic_used(ctx.merchant_id),
                "quota": state.own.strategic_quota(ctx.merchant_id),
                "at_risk": [r.customer_enterprise_id for r in at_risk]}

    @app.get("/relations/arbitrate/{customer_id}")
    def arbitrate(customer_id: int, ctx: MerchantContext = Depends(auth)):
        rel = state.own.arbitrate(customer_id)
        return {"customer_id": customer_id, "owned": rel is not None,
                "owner_merchant_id": rel.merchant_id if rel else None}

    @app.get("/gateway/access")
    def check_access(customer_id: int, ctx: MerchantContext = Depends(auth)):
        """以"已鉴权商家"为 actor 判定访问权限，无法伪造他人身份。"""
        allowed = state.gw.can_access_customer(ctx.merchant_id, customer_id, datetime.now())
        return {"actor_merchant_id": ctx.merchant_id, "customer_id": customer_id,
                "allowed": allowed}

    @app.get("/audit/{customer_id}")
    def audit(customer_id: int, ctx: MerchantContext = Depends(auth)):
        if not state.gw.can_access_customer(ctx.merchant_id, customer_id, datetime.now(),
                                            action="view"):
            raise HTTPException(403, "无权查看该客户审计")
        return [{"actor_merchant_id": a.actor_merchant_id, "action": a.action,
                 "result": a.result, "reason": a.reason}
                for a in state.gw.access_log_for_customer(customer_id)]

    @app.get("/my/customers")
    def my_customers(ctx: MerchantContext = Depends(auth)):
        out = []
        for r in state.store.relations_of_merchant(ctx.merchant_id):
            ent = state.store.enterprises.get(r.customer_enterprise_id)
            out.append({"customer_enterprise_id": r.customer_enterprise_id,
                        "name": ent.name if ent else "",
                        "relation_type": r.relation_type.value,
                        "is_strategic": r.is_strategic,
                        "visibility": r.visibility.value,
                        "status": r.status.value})
        return out

    # ---------------- 撮合（需鉴权）----------------
    @app.post("/match/listing/{listing_id}", response_model=list[MatchOut])
    def match_listing(listing_id: int, top_n: int = 5, ctx: MerchantContext = Depends(auth)):
        listing = state.store.listings.get(listing_id)
        if listing is None:
            raise HTTPException(404, "listing not found")
        if listing.merchant_id != ctx.merchant_id:
            raise HTTPException(403, "只能为自己的货源做撮合")
        return [MatchOut(demand_id=r.demand.demand_id, listing_id=listing_id,
                         buyer_enterprise_id=r.demand.enterprise_id, score=r.score,
                         rationale=r.rationale)
                for r in state.match.match_for_listing(listing, top_n=top_n)]

    @app.post("/match/demand/{demand_id}", response_model=list[MatchOut])
    def match_demand(demand_id: int, top_n: int = 5, ctx: MerchantContext = Depends(auth)):
        demand = state.store.demands.get(demand_id)
        if demand is None:
            raise HTTPException(404, "demand not found")
        return [MatchOut(demand_id=demand_id, listing_id=r.listing.listing_id,
                         buyer_enterprise_id=demand.enterprise_id, score=r.score,
                         rationale=r.rationale)
                for r in state.match.match_for_demand(demand, top_n=top_n)]

    # ---------------- 信用 / 锁价 / 挽回 / 运营（需鉴权）----------------
    @app.post("/credit/terms")
    def credit_terms(body: CreditIn, ctx: MerchantContext = Depends(auth)):
        cp = CreditProfile(enterprise_id=body.enterprise_id, repayment_on_time=body.repayment_on_time,
                           overdue_count=body.overdue_count, fulfillment_rate=body.fulfillment_rate,
                           cancel_rate=body.cancel_rate, years_in_business=body.years_in_business)
        score, tier = score_credit(cp)
        rec = recommend_terms(cp, body.order_amount)
        return {"score": score, "tier": tier, "account_period_days": rec.account_period_days,
                "credit_limit": rec.credit_limit, "require_prepay_ratio": rec.require_prepay_ratio,
                "rationale": rec.rationale}

    @app.post("/triggers/restock")
    def restock(repurchase_cycle_days: int = 18, ctx: MerchantContext = Depends(auth)):
        notes = state.trig.restock_reminders(ctx.merchant_id, datetime.now(), repurchase_cycle_days)
        return [{"customer_enterprise_id": n.customer_enterprise_id, "channel": n.channel,
                 "message": n.message} for n in notes]

    @app.post("/pricelock")
    def create_lock(body: PriceLockIn, ctx: MerchantContext = Depends(auth)):
        now = datetime.now()
        r = state.lock.create_lock(body.buyer_enterprise_id, body.listing_id, body.price,
                                   body.quantity, body.duration_hours, now, body.volatility)
        if not r.ok:
            raise HTTPException(400, r.reason)
        return {"lock_id": r.lock.lock_id, "locked_price": r.lock.locked_price,
                "margin": r.lock.margin, "expires_at": r.lock.expires_at.isoformat()}

    @app.post("/pricelock/{lock_id}/exercise")
    def exercise_lock(lock_id: int, ctx: MerchantContext = Depends(auth)):
        r = state.lock.exercise(lock_id, datetime.now())
        if not r.ok:
            raise HTTPException(400, r.reason)
        return {"lock_id": lock_id, "status": r.lock.status.value}

    @app.post("/recovery/plan")
    def recovery_plan(body: RecoveryIn, ctx: MerchantContext = Depends(auth)):
        now = datetime.now()
        ctx_ab = AbandonContext(
            buyer_enterprise_id=body.buyer_enterprise_id, quoted_price=body.quoted_price,
            buyer_hist_avg_price=body.buyer_hist_avg_price, market_avg_price=body.market_avg_price,
            requested_longer_terms=body.requested_longer_terms,
            delivery_distance_far=body.delivery_distance_far, price_sensitivity=body.price_sensitivity,
            inquired_at=now - timedelta(hours=body.hours_since_inquiry), now=now)
        plan = state.recovery.make_plan(ctx_ab)
        if plan is None:
            return {"stuck": False}
        return {"stuck": True, "blocker": plan.blocker.value, "action": plan.action,
                "needs_human_confirm": plan.needs_human_confirm, "message": plan.message}

    @app.post("/admin/persist")
    def persist(ctx: MerchantContext = Depends(auth)):
        state.persist()
        return {"persisted": state.conn is not None}

    # ---------------- 静态前端 ----------------
    if os.path.isdir(FRONTEND_DIR):
        app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")

    return app


app = create_app(db_path=os.environ.get("STEEL_DB"))
