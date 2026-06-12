import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steel_platform.ranking import FeedbackStore, LogisticRanker


def synth_store(n: int = 200) -> FeedbackStore:
    """合成反馈：转化主要由 price 与 credit 驱动。"""
    store = FeedbackStore()
    rng = [i / n for i in range(n)]
    for i, t in enumerate(rng):
        price = (i * 37 % 100) / 100
        credit = (i * 53 % 100) / 100
        region = (i * 17 % 100) / 100
        history = (i * 29 % 100) / 100
        urgency = (i * 11 % 100) / 100
        # 真实转化倾向：price 与 credit 高则更可能转化
        prob = 0.6 * price + 0.4 * credit
        label = 1 if prob > 0.5 else 0
        store.record(
            {"price": price, "region": region, "history": history,
             "credit": credit, "urgency": urgency},
            label,
        )
    return store


class TestRanking(unittest.TestCase):
    def test_untrained_predicts_half(self):
        r = LogisticRanker()
        self.assertAlmostEqual(r.predict({"price": 1, "credit": 1}), 0.5, places=6)

    def test_training_improves_auc(self):
        store = synth_store()
        r = LogisticRanker()
        before = r.auc(store)
        r.train(store, epochs=300)
        after = r.auc(store)
        self.assertTrue(r.trained)
        self.assertGreater(after, before)
        self.assertGreater(after, 0.85)

    def test_learns_price_credit_importance(self):
        r = LogisticRanker().train(synth_store(), epochs=300)
        # price 与 credit 的权重应为正且明显大于无关特征
        self.assertGreater(r.w["price"], r.w["region"])
        self.assertGreater(r.w["credit"], r.w["history"])

    def test_empty_store_no_crash(self):
        r = LogisticRanker().train(FeedbackStore())
        self.assertFalse(r.trained)


if __name__ == "__main__":
    unittest.main()
