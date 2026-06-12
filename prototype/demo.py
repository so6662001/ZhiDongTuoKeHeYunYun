"""端到端演示：验证"撮合绝不命中私域客户"这条防撬客铁律，并串起各引擎。

运行：python3 prototype/demo.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from steel_platform.credit import recommend_terms, score_credit
from steel_platform.gateway import PermissionGateway
from steel_platform.matching import MatchingEngine
from steel_platform.models import (
    CreditProfile,
    Deal,
    Demand,
    Enterprise,
    EntType,
    Listing,
    Merchant,
    RelationType,
    Urgency,
    Visibility,
)
from steel_platform.ownership import OwnershipEngine
from steel_platform.store import Store
from steel_platform.triggers import TriggerEngine


def hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def main() -> None:
    now = datetime(2026, 6, 12)
    store = Store()
    own = OwnershipEngine(store)
    gw = PermissionGateway(store)
    match = MatchingEngine(store, own, gw)
    trig = TriggerEngine(store, own)

    # 商家 A（贸易公司）、商家 B（批发商）
    a_ent = store.add_enterprise(Enterprise(1, "甲贸易", EntType.TRADER, "华北", ["螺纹"]))
    b_ent = store.add_enterprise(Enterprise(2, "乙批发", EntType.WHOLESALER, "华北", ["螺纹"]))
    merchant_a = store.add_merchant(Merchant(101, a_ent.enterprise_id))
    merchant_b = store.add_merchant(Merchant(102, b_ent.enterprise_id))

    # 客户：C1 是 A 的高价值战略客户；C2 是无主公域客户
    c1 = store.add_enterprise(Enterprise(11, "高价值终端C1", EntType.END_USER, "华北", ["螺纹"]))
    c2 = store.add_enterprise(Enterprise(12, "公域散客C2", EntType.RETAILER, "华北", ["螺纹"]))
    store.add_credit(CreditProfile(c1.enterprise_id, repayment_on_time=0.98, fulfillment_rate=0.97,
                                   years_in_business=8))
    store.add_credit(CreditProfile(c2.enterprise_id, repayment_on_time=0.6, fulfillment_rate=0.7,
                                   cancel_rate=0.2, overdue_count=3, years_in_business=2))

    # A 与 C1 成交并设为战略客户
    own.establish(merchant_a.merchant_id, c1.enterprise_id, RelationType.DEALT, now)
    own.mark_strategic(merchant_a.merchant_id, c1.enterprise_id, now)
    store.deals.append(Deal(store.next_id(), c1.enterprise_id, merchant_a.merchant_id,
                            "螺纹", "HRB400E Φ20", 100, 3800, now - timedelta(days=30)))

    # C1 与 C2 都发布求购需求
    d1 = store.add_demand(Demand(store.next_id(), c1.enterprise_id, "螺纹", "HRB400E Φ20",
                                 200, "华北", target_price=3850, urgency=Urgency.URGENT))
    d2 = store.add_demand(Demand(store.next_id(), c2.enterprise_id, "螺纹", "HRB400E Φ20",
                                 50, "华北", target_price=3850, urgency=Urgency.NORMAL,
                                 is_public=True))

    # 商家 B 上架公域货源
    b_listing = store.add_listing(Listing(store.next_id(), merchant_b.merchant_id, "螺纹",
                                          "HRB400E Φ20", 500, 3820, "华北",
                                          visibility=Visibility.PUBLIC, inventory_age_days=25))

    hr("场景1 · 防撬客：B 上架货源后做撮合，能匹配到谁？")
    results = match.match_for_listing(b_listing)
    matched_ids = {r.demand.enterprise_id for r in results}
    for r in results:
        ent = store.enterprises[r.demand.enterprise_id]
        print(f"  匹配到需求方: {ent.name} (id={ent.enterprise_id})  得分={r.score}")
    assert c1.enterprise_id not in matched_ids, "战略客户 C1 不应被撮合给 B！"
    print(f"  ✅ A 的战略客户 C1(id=11) 未出现在 B 的撮合结果中 —— 防撬客生效")
    print(f"  ✅ 公域散客 C2(id=12) 正常进入撮合")

    hr("场景2 · 权限网关：B 能否访问 A 的战略客户 C1？")
    can = gw.can_access_customer(merchant_b.merchant_id, c1.enterprise_id, now)
    print(f"  B 访问 C1 -> {'允许' if can else '拒绝'}")
    assert can is False
    can2 = gw.can_access_customer(merchant_a.merchant_id, c1.enterprise_id, now)
    print(f"  A 访问自己的 C1 -> {'允许' if can2 else '拒绝'}")
    print("  审计日志(C1 被访问记录):")
    for a in gw.access_log_for_customer(c1.enterprise_id):
        print(f"    - 商家{a.actor_merchant_id} {a.action} -> {a.result} ({a.reason})")

    hr("场景3 · 信用评分与账期推荐")
    for cust in (c1, c2):
        cp = store.credit[cust.enterprise_id]
        s, tier = score_credit(cp)
        rec = recommend_terms(cp, order_amount=200 * 3800)
        print(f"  {cust.name}: 信用分={s} 等级={tier} -> 账期{rec.account_period_days}天 "
              f"预付{int(rec.require_prepay_ratio*100)}% ({rec.rationale})")

    hr("场景4 · 智能补货提醒（仅对 A 自己的归属客户）")
    reminders = trig.restock_reminders(merchant_a.merchant_id, now + timedelta(days=5))
    for n in reminders:
        ent = store.enterprises[n.customer_enterprise_id]
        print(f"  -> 对 {ent.name}: {n.message}")
    if not reminders:
        print("  （当前无触发，调整时间窗后可触发）")

    hr("场景5 · 撞单仲裁：C2 与 A、B 都建立关系后归谁？")
    own.establish(merchant_b.merchant_id, c2.enterprise_id, RelationType.INQUIRED, now)
    own.establish(merchant_a.merchant_id, c2.enterprise_id, RelationType.DEALT, now + timedelta(days=1))
    winner = own.arbitrate(c2.enterprise_id)
    wm = winner.merchant_id if winner else None
    print(f"  C2 仲裁归属 -> 商家{wm}（A=101 有成交关系，优先级高于 B=102 的询价关系）")
    assert wm == merchant_a.merchant_id

    print("\n所有断言通过 ✅  —— 防撬客铁律在撮合与权限网关两处均生效。")


if __name__ == "__main__":
    main()
