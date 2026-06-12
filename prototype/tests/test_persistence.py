import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
from steel_platform.persistence import connect, load_store, save_store
from steel_platform.store import Store

NOW = datetime(2026, 6, 12)


class TestPersistence(unittest.TestCase):
    def _build_store(self) -> Store:
        store = Store()
        own = OwnershipEngine(store)
        store.add_enterprise(Enterprise(1, "甲贸易", EntType.TRADER, "华北", ["螺纹"]))
        store.add_enterprise(Enterprise(11, "C1", EntType.END_USER, "华北", ["螺纹"]))
        store.add_merchant(Merchant(101, 1))
        store.add_listing(Listing(2001, 101, "螺纹", "HRB400E Φ20", 500, 3820, "华北",
                                  visibility=Visibility.PUBLIC))
        store.add_demand(Demand(1001, 11, "螺纹", "HRB400E Φ20", 100, "华北",
                                target_price=3850, urgency=Urgency.URGENT))
        store.add_credit(CreditProfile(11, repayment_on_time=0.98, fulfillment_rate=0.97,
                                       years_in_business=8, score=93, tier="A"))
        store.deals.append(Deal(9001, 11, 101, "螺纹", "HRB400E Φ20", 100, 3800, NOW))
        own.establish(101, 11, RelationType.DEALT, NOW)
        own.mark_strategic(101, 11, NOW)
        return store

    def test_schema_init_creates_tables(self):
        conn = connect()
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("customer_relation", names)
        self.assertIn("access_audit", names)

    def test_round_trip_preserves_data(self):
        store = self._build_store()
        conn = connect()
        save_store(store, conn)
        loaded = load_store(conn)

        self.assertEqual(len(loaded.enterprises), len(store.enterprises))
        self.assertEqual(len(loaded.listings), 1)
        self.assertEqual(len(loaded.deals), 1)
        rel = loaded.relation_of(101, 11)
        self.assertIsNotNone(rel)
        self.assertTrue(rel.is_strategic)
        self.assertEqual(rel.visibility, Visibility.PRIVATE)
        self.assertEqual(loaded.credit[11].tier, "A")

    def test_ownership_works_after_reload(self):
        store = self._build_store()
        conn = connect()
        save_store(store, conn)
        loaded = load_store(conn)
        own = OwnershipEngine(loaded)
        winner = own.arbitrate(11)
        self.assertEqual(winner.merchant_id, 101)
        # 重载后新建实体的 id 不与旧 id 冲突
        self.assertGreater(loaded.next_id(), 9001)

    def test_persist_to_file(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        store = self._build_store()
        conn = connect(path)
        save_store(store, conn)
        conn.close()
        conn2 = connect(path)  # init 幂等
        loaded = load_store(conn2)
        self.assertEqual(len(loaded.demands), 1)


if __name__ == "__main__":
    unittest.main()
