import unittest
from datetime import timedelta

from base import NOW, build

from steel_platform.credit import recommend_terms, score_credit
from steel_platform.models import (
    CreditProfile,
    Deal,
    Enterprise,
    EntType,
    Merchant,
    RelationType,
)


class TestCredit(unittest.TestCase):
    def test_high_credit_gets_terms(self):
        cp = CreditProfile(1, repayment_on_time=0.98, fulfillment_rate=0.97, years_in_business=8)
        score, tier = score_credit(cp)
        self.assertGreaterEqual(score, 80)
        self.assertEqual(tier, "A")
        rec = recommend_terms(cp, 100000)
        self.assertGreater(rec.account_period_days, 0)
        self.assertEqual(rec.require_prepay_ratio, 0.0)

    def test_low_credit_requires_prepay(self):
        cp = CreditProfile(2, repayment_on_time=0.4, fulfillment_rate=0.6, cancel_rate=0.3,
                           overdue_count=6, years_in_business=1)
        score, tier = score_credit(cp)
        self.assertIn(tier, ("C", "D"))
        rec = recommend_terms(cp, 100000)
        self.assertGreater(rec.require_prepay_ratio, 0.0)


class TestTriggers(unittest.TestCase):
    def setUp(self):
        self.store, self.own, _, _, self.trig = build()
        self.store.add_merchant(Merchant(101, 1))
        self.store.add_enterprise(Enterprise(11, "门零客户", EntType.RETAILER, "华北", ["螺纹"]))
        self.own.establish(101, 11, RelationType.DEALT, NOW)

    def test_restock_reminder_fires_after_cycle(self):
        self.store.deals.append(Deal(1, 11, 101, "螺纹", "Φ20", 50, 3800, NOW))
        # 复购周期18天，*1.2=21.6天后应触发
        out = self.trig.restock_reminders(101, NOW + timedelta(days=25))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].trigger, "restock_reminder")

    def test_restock_not_fire_within_cycle(self):
        self.store.deals.append(Deal(1, 11, 101, "螺纹", "Φ20", 50, 3800, NOW))
        out = self.trig.restock_reminders(101, NOW + timedelta(days=10))
        self.assertEqual(len(out), 0)

    def test_price_anomaly_targets_followers(self):
        out = self.trig.price_anomaly_reminders(101, "螺纹", -80, NOW)
        self.assertEqual(len(out), 1)
        out2 = self.trig.price_anomaly_reminders(101, "螺纹", -10, NOW)
        self.assertEqual(len(out2), 0)  # 低于阈值不触发


if __name__ == "__main__":
    unittest.main()
