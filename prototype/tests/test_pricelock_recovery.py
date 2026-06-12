import unittest
from datetime import datetime, timedelta

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steel_platform.pricelock import LockStatus, PriceLockEngine
from steel_platform.recovery import AbandonContext, Blocker, RecoveryEngine

NOW = datetime(2026, 6, 12, 9, 0, 0)


class TestPriceLock(unittest.TestCase):
    def setUp(self):
        self.engine = PriceLockEngine(exposure_limit_tons=1000)

    def test_create_and_exercise(self):
        r = self.engine.create_lock(11, 2001, 3820, 200, 6, NOW)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.lock.margin, 3820 * 200 * 0.01, places=2)
        ex = self.engine.exercise(r.lock.lock_id, NOW + timedelta(hours=5))
        self.assertTrue(ex.ok)
        self.assertEqual(ex.lock.status, LockStatus.EXERCISED)

    def test_expire_after_duration(self):
        r = self.engine.create_lock(11, 2001, 3820, 200, 6, NOW)
        ex = self.engine.exercise(r.lock.lock_id, NOW + timedelta(hours=7))
        self.assertFalse(ex.ok)
        self.assertEqual(ex.lock.status, LockStatus.EXPIRED)

    def test_high_volatility_limits_duration(self):
        r = self.engine.create_lock(11, 2001, 3820, 100, 24, NOW, volatility=0.06)
        self.assertFalse(r.ok)
        r2 = self.engine.create_lock(11, 2001, 3820, 100, 2, NOW, volatility=0.06)
        self.assertTrue(r2.ok)

    def test_exposure_limit(self):
        self.assertTrue(self.engine.create_lock(11, 2001, 3800, 800, 6, NOW).ok)
        over = self.engine.create_lock(12, 2002, 3800, 300, 6, NOW)
        self.assertFalse(over.ok)

    def test_expire_due_releases(self):
        self.engine.create_lock(11, 2001, 3800, 100, 2, NOW)
        released = self.engine.expire_due(NOW + timedelta(hours=3))
        self.assertEqual(len(released), 1)


class TestRecovery(unittest.TestCase):
    def setUp(self):
        self.engine = RecoveryEngine()

    def _ctx(self, **kw):
        base = dict(
            buyer_enterprise_id=11,
            quoted_price=3900,
            buyer_hist_avg_price=3800,
            market_avg_price=3820,
            requested_longer_terms=False,
            delivery_distance_far=False,
            price_sensitivity=0.5,
            inquired_at=NOW,
            now=NOW + timedelta(hours=25),
        )
        base.update(kw)
        return AbandonContext(**base)

    def test_not_stuck_returns_none(self):
        self.assertIsNone(self.engine.make_plan(self._ctx(now=NOW + timedelta(hours=2))))

    def test_price_blocker(self):
        plan = self.engine.make_plan(self._ctx(quoted_price=3950))
        self.assertEqual(plan.blocker, Blocker.PRICE)
        self.assertTrue(plan.needs_human_confirm)

    def test_terms_blocker(self):
        plan = self.engine.make_plan(
            self._ctx(quoted_price=3800, requested_longer_terms=True)
        )
        self.assertEqual(plan.blocker, Blocker.TERMS)

    def test_logistics_blocker(self):
        plan = self.engine.make_plan(
            self._ctx(quoted_price=3800, delivery_distance_far=True)
        )
        self.assertEqual(plan.blocker, Blocker.LOGISTICS)
        self.assertFalse(plan.needs_human_confirm)

    def test_watching_blocker(self):
        plan = self.engine.make_plan(self._ctx(quoted_price=3790))
        self.assertEqual(plan.blocker, Blocker.WATCHING)


if __name__ == "__main__":
    unittest.main()
