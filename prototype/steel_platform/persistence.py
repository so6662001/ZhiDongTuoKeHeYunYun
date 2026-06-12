"""SQLite 持久化层：基于 sql/schema.sql 落地真实存储（对应 docs/01）。

提供 init_db / save_store / load_store 三个能力，把内存 Store 与 SQLite 互转。
生产可平移到 PostgreSQL/MySQL（schema.sql 已尽量使用通用方言）。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Optional

from .models import (
    AuditEntry,
    CreditProfile,
    CustomerRelation,
    Deal,
    Demand,
    Enterprise,
    EntType,
    Listing,
    Merchant,
    RelationStatus,
    RelationType,
    Urgency,
    Visibility,
)
from .store import Store

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "sql",
    "schema.sql",
)

_ISO = "%Y-%m-%dT%H:%M:%S"


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(s, _ISO) if s else None


def _s(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime(_ISO) if dt else None


def init_db(conn: sqlite3.Connection, schema_path: str = SCHEMA_PATH) -> None:
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def connect(db_path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def save_store(store: Store, conn: sqlite3.Connection) -> None:
    """把内存 Store 快照写入 SQLite（全量覆盖，幂等）。

    内存模型已保证一致性，快照批量写入时关闭 FK 校验以避免写入顺序约束。
    """
    conn.commit()  # 结束可能的隐式事务，确保 PRAGMA 生效
    conn.execute("PRAGMA foreign_keys=OFF")
    cur = conn.cursor()
    for t in ("access_audit", "deal", "credit_profile", "customer_relation",
              "demand", "listing", "merchant", "enterprise"):
        cur.execute(f"DELETE FROM {t}")

    for e in store.enterprises.values():
        cur.execute(
            "INSERT INTO enterprise(enterprise_id,name,ent_type,scale,region_code,"
            "main_categories,credit_score,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (e.enterprise_id, e.name, e.ent_type.value, e.scale, e.region_code,
             json.dumps(e.main_categories, ensure_ascii=False), e.credit_score,
             _s(datetime.now())),
        )
    for m in store.merchants.values():
        cur.execute(
            "INSERT INTO merchant(merchant_id,enterprise_id,tier,created_at) VALUES(?,?,?,?)",
            (m.merchant_id, m.enterprise_id, m.tier, _s(datetime.now())),
        )
    for l in store.listings.values():
        cur.execute(
            "INSERT INTO listing(listing_id,merchant_id,category,spec,quantity,price,"
            "price_type,warehouse_region,account_period_days,visibility,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (l.listing_id, l.merchant_id, l.category, l.spec, l.quantity, l.price,
             l.price_type, l.warehouse_region, l.account_period_days,
             l.visibility.value, l.status, _s(datetime.now())),
        )
    for d in store.demands.values():
        cur.execute(
            "INSERT INTO demand(demand_id,enterprise_id,category,spec,quantity,target_price,"
            "delivery_region,urgency,is_public,valid_until,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (d.demand_id, d.enterprise_id, d.category, d.spec, d.quantity, d.target_price,
             d.delivery_region, d.urgency.value, 1 if d.is_public else 0,
             _s(d.valid_until), _s(datetime.now())),
        )
    for r in store.relations.values():
        cur.execute(
            "INSERT INTO customer_relation(relation_id,merchant_id,customer_enterprise_id,"
            "relation_type,is_strategic,protect_until,visibility,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (r.relation_id, r.merchant_id, r.customer_enterprise_id, r.relation_type.value,
             1 if r.is_strategic else 0, _s(r.protect_until), r.visibility.value,
             r.status.value, _s(r.created_at)),
        )
    for c in store.credit.values():
        cur.execute(
            "INSERT INTO credit_profile(enterprise_id,repayment_on_time,overdue_count,"
            "fulfillment_rate,cancel_rate,years_in_business,score,tier,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (c.enterprise_id, c.repayment_on_time, c.overdue_count, c.fulfillment_rate,
             c.cancel_rate, c.years_in_business, c.score, c.tier, _s(datetime.now())),
        )
    for d in store.deals:
        cur.execute(
            "INSERT INTO deal(deal_id,buyer_enterprise_id,seller_merchant_id,category,spec,"
            "quantity,price,account_period_days,repaid,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (d.deal_id, d.buyer_enterprise_id, d.seller_merchant_id, d.category, d.spec,
             d.quantity, d.price, d.account_period_days, 1 if d.repaid else 0, _s(d.created_at)),
        )
    for a in store.audit:
        cur.execute(
            "INSERT INTO access_audit(actor_merchant_id,target_customer_id,action,channel,"
            "result,reason,occurred_at) VALUES(?,?,?,?,?,?,?)",
            (a.actor_merchant_id, a.target_customer_id, a.action, a.channel,
             a.result, a.reason, _s(a.occurred_at)),
        )
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def load_store(conn: sqlite3.Connection) -> Store:
    """从 SQLite 读出快照重建内存 Store。"""
    store = Store()
    max_id = 0
    for row in conn.execute("SELECT * FROM enterprise"):
        store.add_enterprise(Enterprise(
            enterprise_id=row["enterprise_id"], name=row["name"],
            ent_type=EntType(row["ent_type"]), region_code=row["region_code"],
            main_categories=json.loads(row["main_categories"] or "[]"),
            scale=row["scale"] or "small", credit_score=row["credit_score"] or 60))
        max_id = max(max_id, row["enterprise_id"])
    for row in conn.execute("SELECT * FROM merchant"):
        store.add_merchant(Merchant(row["merchant_id"], row["enterprise_id"],
                                    row["tier"] or "standard"))
        max_id = max(max_id, row["merchant_id"])
    for row in conn.execute("SELECT * FROM listing"):
        store.add_listing(Listing(
            listing_id=row["listing_id"], merchant_id=row["merchant_id"],
            category=row["category"], spec=row["spec"], quantity=row["quantity"],
            price=row["price"], warehouse_region=row["warehouse_region"],
            price_type=row["price_type"] or "negotiable",
            account_period_days=row["account_period_days"] or 0,
            visibility=Visibility(row["visibility"]), status=row["status"]))
        max_id = max(max_id, row["listing_id"])
    for row in conn.execute("SELECT * FROM demand"):
        store.add_demand(Demand(
            demand_id=row["demand_id"], enterprise_id=row["enterprise_id"],
            category=row["category"], spec=row["spec"], quantity=row["quantity"],
            delivery_region=row["delivery_region"], target_price=row["target_price"],
            urgency=Urgency(row["urgency"] or "normal"),
            is_public=bool(row["is_public"]), valid_until=_dt(row["valid_until"])))
        max_id = max(max_id, row["demand_id"])
    for row in conn.execute("SELECT * FROM customer_relation"):
        store.add_relation(CustomerRelation(
            relation_id=row["relation_id"], merchant_id=row["merchant_id"],
            customer_enterprise_id=row["customer_enterprise_id"],
            relation_type=RelationType(row["relation_type"]),
            created_at=_dt(row["created_at"]) or datetime.now(),
            protect_until=_dt(row["protect_until"]),
            is_strategic=bool(row["is_strategic"]),
            visibility=Visibility(row["visibility"]),
            status=RelationStatus(row["status"])))
        max_id = max(max_id, row["relation_id"])
    for row in conn.execute("SELECT * FROM credit_profile"):
        store.add_credit(CreditProfile(
            enterprise_id=row["enterprise_id"],
            repayment_on_time=row["repayment_on_time"] if row["repayment_on_time"] is not None else 1.0,
            overdue_count=row["overdue_count"] or 0,
            fulfillment_rate=row["fulfillment_rate"] if row["fulfillment_rate"] is not None else 1.0,
            cancel_rate=row["cancel_rate"] or 0.0,
            years_in_business=row["years_in_business"] or 1,
            score=row["score"] or 60, tier=row["tier"] or "B"))
    for row in conn.execute("SELECT * FROM deal"):
        store.deals.append(Deal(
            deal_id=row["deal_id"], buyer_enterprise_id=row["buyer_enterprise_id"],
            seller_merchant_id=row["seller_merchant_id"], category=row["category"],
            spec=row["spec"], quantity=row["quantity"], price=row["price"],
            created_at=_dt(row["created_at"]) or datetime.now(),
            account_period_days=row["account_period_days"] or 0,
            repaid=bool(row["repaid"])))
        max_id = max(max_id, row["deal_id"])
    for row in conn.execute("SELECT * FROM access_audit"):
        store.audit.append(AuditEntry(
            actor_merchant_id=row["actor_merchant_id"],
            target_customer_id=row["target_customer_id"], action=row["action"],
            result=row["result"], reason=row["reason"],
            occurred_at=_dt(row["occurred_at"]) or datetime.now(),
            channel=row["channel"] or "api"))
    store._seq = max_id
    return store
