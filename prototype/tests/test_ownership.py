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
from steel_platform.ownership import StrategicConflict


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

    def test_strategic_never_expires(self):
        self.own.mark_strategic(101, 11, NOW)
        self.own.refresh_states(NOW + timedelta(days=9999))
        self.assertEqual(self.store.relation_of(101, 11).status, RelationStatus.ACTIVE)

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
