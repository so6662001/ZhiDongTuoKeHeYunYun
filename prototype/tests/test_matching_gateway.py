import unittest

from base import NOW, build

from steel_platform.models import (
    Demand,
    Enterprise,
    EntType,
    Listing,
    Merchant,
    RelationType,
    Urgency,
    Visibility,
)


class TestMatchingAndGateway(unittest.TestCase):
    def setUp(self):
        self.store, self.own, self.gw, self.match, _ = build()
        self.store.add_merchant(Merchant(101, 1))
        self.store.add_merchant(Merchant(102, 2))
        # 战略客户 C1 与公域客户 C2
        self.store.add_enterprise(Enterprise(11, "C1", EntType.END_USER, "华北", ["螺纹"]))
        self.store.add_enterprise(Enterprise(12, "C2", EntType.RETAILER, "华北", ["螺纹"]))
        self.own.establish(101, 11, RelationType.DEALT, NOW)
        self.own.mark_strategic(101, 11, NOW)
        self.d1 = self.store.add_demand(
            Demand(1001, 11, "螺纹", "HRB400E Φ20", 100, "华北", target_price=3850)
        )
        self.d2 = self.store.add_demand(
            Demand(1002, 12, "螺纹", "HRB400E Φ20", 50, "华北", target_price=3850, is_public=True)
        )
        self.listing = self.store.add_listing(
            Listing(2001, 102, "螺纹", "HRB400E Φ20", 500, 3820, "华北",
                    visibility=Visibility.PUBLIC)
        )

    def test_matching_excludes_strategic_customer(self):
        results = self.match.match_for_listing(self.listing)
        ids = {r.demand.enterprise_id for r in results}
        self.assertNotIn(11, ids)  # 战略客户绝不被撮合
        self.assertIn(12, ids)     # 公域客户正常匹配

    def test_gateway_blocks_competitor_access(self):
        self.assertFalse(self.gw.can_access_customer(102, 11, NOW))  # B 看不到 A 的战略客户
        self.assertTrue(self.gw.can_access_customer(101, 11, NOW))   # A 看得到自己的客户

    def test_gateway_allows_public_customer(self):
        self.assertTrue(self.gw.can_access_customer(102, 12, NOW))

    def test_public_listings_only(self):
        self.store.add_listing(
            Listing(2002, 101, "螺纹", "HRB400E Φ20", 300, 3810, "华北",
                    visibility=Visibility.PRIVATE)
        )
        pub = self.gw.public_listings()
        self.assertTrue(all(l.visibility == Visibility.PUBLIC for l in pub))

    def test_audit_logged(self):
        self.gw.can_access_customer(102, 11, NOW)
        log = self.gw.access_log_for_customer(11)
        self.assertTrue(any(a.result == "denied" for a in log))


if __name__ == "__main__":
    unittest.main()
