import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    Visibility,
)
from steel_platform.ownership import NotEligibleStrategic, OwnershipEngine, QuotaExceeded
from steel_platform.store import Store
from steel_platform import value as value_model

NOW = datetime(2026, 6, 12)


def make_store():
    s = Store()
    s.add_merchant(Merchant(101, 1))
    s.add_merchant(Merchant(102, 2))
    return s


class TestValueModel(unittest.TestCase):
    def test_high_value_customer_scores_high(self):
        s = make_store()
        s.add_enterprise(Enterprise(11, "大客户", EntType.END_USER, "华北", ["螺纹"]))
        s.add_credit(CreditProfile(11, repayment_on_time=0.98))
        for i in range(12):  # 高频高额成交
            s.deals.append(Deal(s.next_id(), 11, 101, "螺纹", "Φ20", 200, 3800,
                                NOW - timedelta(days=i * 25)))
        score = value_model.customer_value_score(s, 101, 11, NOW)
        self.assertGreater(score, 60)

    def test_no_history_low_score(self):
        s = make_store()
        s.add_enterprise(Enterprise(12, "新客", EntType.RETAILER, "华北", []))
        self.assertLess(value_model.customer_value_score(s, 101, 12, NOW), 40)

    def test_dynamic_capacity_scales_with_size(self):
        small = make_store()
        own_s = OwnershipEngine(small)
        # 小商家：少量客户 -> 保底容量
        for cid in range(11, 14):
            small.add_enterprise(Enterprise(cid, f"c{cid}", EntType.RETAILER, "华北", []))
            own_s.establish(101, cid, RelationType.DEALT, NOW)
        self.assertEqual(own_s.strategic_capacity(101), 5)  # base

        big = make_store()
        own_b = OwnershipEngine(big)
        for cid in range(1000, 1200):  # 200 个活跃客户
            big.add_enterprise(Enterprise(cid, f"c{cid}", EntType.RETAILER, "华北", []))
            own_b.establish(101, cid, RelationType.DEALT, NOW)
        self.assertEqual(own_b.strategic_capacity(101), 20)  # 200 * 10%


class TestValueGate(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.own = OwnershipEngine(self.store, value_gate=True)
        self.store.add_enterprise(Enterprise(11, "高价值", EntType.END_USER, "华北", ["螺纹"]))
        self.store.add_enterprise(Enterprise(12, "低价值", EntType.RETAILER, "华北", []))
        self.store.add_credit(CreditProfile(11, repayment_on_time=0.98))
        for i in range(10):
            self.store.deals.append(Deal(self.store.next_id(), 11, 101, "螺纹", "Φ20",
                                         200, 3800, NOW - timedelta(days=i * 20)))
        self.own.establish(101, 11, RelationType.DEALT, NOW)
        self.own.establish(101, 12, RelationType.IMPORTED, NOW)

    def test_high_value_can_be_strategic(self):
        rel = self.own.mark_strategic(101, 11, NOW)
        self.assertTrue(rel.is_strategic)

    def test_low_value_rejected_by_gate(self):
        with self.assertRaises(NotEligibleStrategic):
            self.own.mark_strategic(101, 12, NOW)

    def test_eligibility_report(self):
        e = self.own.strategic_eligibility(101, 11, NOW)
        self.assertTrue(e["ok"])
        self.assertGreaterEqual(e["value_score"], 40)


class TestBuyerSourcingFreedom(unittest.TestCase):
    """买方主权：私域/战略买方主动公开寻源时，可向他家询价，老关系享优先响应权。"""

    def setUp(self):
        self.store = make_store()
        self.own = OwnershipEngine(self.store)
        self.gw = PermissionGateway(self.store)
        self.match = MatchingEngine(self.store, self.own, self.gw)
        # 买方 C1 是商家101 的战略客户
        self.store.add_enterprise(Enterprise(11, "C1", EntType.END_USER, "华北", ["螺纹"]))
        self.own.establish(101, 11, RelationType.DEALT, NOW)
        self.own.mark_strategic(101, 11, NOW)
        # 两家卖家都有公域货源：101(归属) 和 102(他家)
        self.store.add_listing(Listing(2001, 101, "螺纹", "HRB400E Φ20", 500, 3820, "华北",
                                       visibility=Visibility.PUBLIC))
        self.store.add_listing(Listing(2002, 102, "螺纹", "HRB400E Φ20", 500, 3815, "华北",
                                       visibility=Visibility.PUBLIC))

    def test_passive_demand_not_pushed(self):
        # 平台 Push：私域买方的非公开需求 -> 不进撮合（防撬客）
        d = self.store.add_demand(Demand(1001, 11, "螺纹", "HRB400E Φ20", 100, "华北",
                                         target_price=3850, is_public=False))
        self.assertEqual(self.match.match_for_demand(d), [])

    def test_public_sourcing_allows_other_sellers_with_owner_priority(self):
        # 买方 Pull：主动公开寻源 -> 可向他家询价，但归属商家(101)优先
        d = self.store.add_demand(Demand(1002, 11, "螺纹", "HRB400E Φ20", 100, "华北",
                                         target_price=3850, is_public=True))
        res = self.match.match_for_demand(d)
        seller_ids = [r.listing.merchant_id for r in res]
        self.assertIn(102, seller_ids)        # 买方可向他家询价（不被绑死）
        self.assertIn(101, seller_ids)        # 归属商家也在
        self.assertTrue(res[0].priority)      # 归属商家排第一
        self.assertEqual(res[0].listing.merchant_id, 101)


if __name__ == "__main__":
    unittest.main()
