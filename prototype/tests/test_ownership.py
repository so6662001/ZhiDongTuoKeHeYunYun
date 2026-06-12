import unittest
from datetime import timedelta

from base import NOW, build

from steel_platform.models import (
    Enterprise,
    EntType,
    Merchant,
    RelationStatus,
    RelationType,
)
from steel_platform.models import Visibility
from steel_platform.ownership import QuotaExceeded, StrategicConflict


class TestOwnership(unittest.TestCase):
    def setUp(self):
        self.store, self.own, *_ = build()
        self.store.add_enterprise(Enterprise(11, "客户C", EntType.END_USER, "华北", ["螺纹"]))
        self.store.add_merchant(Merchant(101, 1))
        self.store.add_merchant(Merchant(102, 2))

    def test_establish_sets_protect_period(self):
        rel = self.own.establish(101, 11, RelationType.DEALT, NOW)
        self.assertEqual(rel.status, RelationStatus.ACTIVE)
        self.assertEqual(rel.protect_until, NOW + timedelta(days=90))

    def test_expire_then_return_to_pool(self):
        self.own.establish(101, 11, RelationType.IMPORTED, NOW)  # 30天
        self.own.refresh_states(NOW + timedelta(days=31))
        self.assertEqual(self.store.relation_of(101, 11).status, RelationStatus.EXPIRED)
        self.own.refresh_states(NOW + timedelta(days=31 + 31))
        self.assertEqual(
            self.store.relation_of(101, 11).status, RelationStatus.RETURNED_TO_POOL
        )

    def test_interaction_renews(self):
        self.own.establish(101, 11, RelationType.IMPORTED, NOW)
        self.own.refresh_states(NOW + timedelta(days=31))
        self.own.register_interaction(101, 11, NOW + timedelta(days=31))
        self.assertEqual(self.store.relation_of(101, 11).status, RelationStatus.ACTIVE)

    def test_one_way_blast_does_not_renew(self):
        self.own.establish(101, 11, RelationType.IMPORTED, NOW)
        before = self.store.relation_of(101, 11).protect_until
        self.own.register_interaction(101, 11, NOW + timedelta(days=5), two_way=False)
        self.assertEqual(self.store.relation_of(101, 11).protect_until, before)

    def test_strategic_maintained_with_interaction(self):
        self.own.mark_strategic(101, 11, NOW)
        # 持续经营：在宽限期内有真实互动，刷新经营时钟
        self.own.register_interaction(101, 11, NOW + timedelta(days=300))
        self.own.refresh_states(NOW + timedelta(days=500))
        rel = self.store.relation_of(101, 11)
        self.assertTrue(rel.is_strategic)  # 仍是战略客户
        self.assertEqual(rel.visibility, Visibility.PRIVATE)

    def test_strategic_demotes_when_idle_but_not_to_pool(self):
        self.own.mark_strategic(101, 11, NOW)
        # 圈而不耕：超超长宽限期无任何互动 -> 降级
        self.own.refresh_states(NOW + timedelta(days=400))
        rel = self.store.relation_of(101, 11)
        self.assertFalse(rel.is_strategic)                 # 战略身份被收回
        self.assertEqual(rel.visibility, Visibility.PRIVATE)  # 但仍属私域，未直接入公海
        self.assertEqual(rel.status, RelationStatus.ACTIVE)

    def test_strategic_health_states(self):
        self.own.mark_strategic(101, 11, NOW)
        rel = self.store.relation_of(101, 11)
        self.assertEqual(self.own.strategic_health(rel, NOW + timedelta(days=10)), "healthy")
        self.assertEqual(self.own.strategic_health(rel, NOW + timedelta(days=200)), "at_risk")
        self.assertEqual(self.own.strategic_health(rel, NOW + timedelta(days=400)), "demotable")

    def test_strategic_quota_blocks_hoarding(self):
        self.own.set_strategic_quota(101, 2)
        self.store.add_enterprise(Enterprise(12, "C2", EntType.END_USER, "华北", []))
        self.store.add_enterprise(Enterprise(13, "C3", EntType.END_USER, "华北", []))
        self.own.mark_strategic(101, 11, NOW)
        self.own.mark_strategic(101, 12, NOW)
        with self.assertRaises(QuotaExceeded):
            self.own.mark_strategic(101, 13, NOW)  # 超名额，无法把所有客户都圈成战略

    def test_unmark_releases_quota(self):
        self.own.set_strategic_quota(101, 1)
        self.store.add_enterprise(Enterprise(12, "C2", EntType.END_USER, "华北", []))
        self.own.mark_strategic(101, 11, NOW)
        self.own.unmark_strategic(101, 11, NOW)
        rel = self.store.relation_of(101, 11)
        self.assertFalse(rel.is_strategic)
        self.assertEqual(rel.visibility, Visibility.PRIVATE)  # 降级为普通保护，不入公海
        # 名额释放后可再设别人
        self.own.mark_strategic(101, 12, NOW)
        self.assertTrue(self.store.relation_of(101, 12).is_strategic)

    def test_customer_opt_out_to_pool(self):
        self.own.mark_strategic(101, 11, NOW)
        self.own.customer_opt_out(101, 11, NOW)
        rel = self.store.relation_of(101, 11)
        self.assertFalse(rel.is_strategic)
        self.assertEqual(rel.status, RelationStatus.RETURNED_TO_POOL)
        self.assertIsNone(self.own.arbitrate(11))  # 回公海，可被重新撮合/认领

    def test_strategic_mutual_exclusion(self):
        self.own.mark_strategic(101, 11, NOW)
        with self.assertRaises(StrategicConflict):
            self.own.mark_strategic(102, 11, NOW)

    def test_arbitration_prefers_deal_over_inquiry(self):
        self.own.establish(102, 11, RelationType.INQUIRED, NOW)
        self.own.establish(101, 11, RelationType.DEALT, NOW + timedelta(days=1))
        winner = self.own.arbitrate(11)
        self.assertEqual(winner.merchant_id, 101)

    def test_unowned_returns_none(self):
        self.assertIsNone(self.own.arbitrate(11))
        self.assertFalse(self.own.is_owned(11))


if __name__ == "__main__":
    unittest.main()
