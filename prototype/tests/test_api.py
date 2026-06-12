import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi.testclient import TestClient
    from api.app import create_app
    HAS_FASTAPI = True
except Exception:  # pragma: no cover
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi 未安装")
class TestApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def _seed(self):
        c = self.client
        c.post("/merchants", json={"merchant_id": 101, "enterprise_id": 1})
        c.post("/merchants", json={"merchant_id": 102, "enterprise_id": 2})
        c.post("/enterprises", json={"enterprise_id": 11, "name": "C1",
                                     "ent_type": "end_user", "region_code": "华北",
                                     "main_categories": ["螺纹"]})
        c.post("/enterprises", json={"enterprise_id": 12, "name": "C2",
                                     "ent_type": "retailer", "region_code": "华北",
                                     "main_categories": ["螺纹"]})
        c.post("/relations", json={"merchant_id": 101, "customer_enterprise_id": 11,
                                   "relation_type": "dealt"})
        c.post("/relations/strategic", json={"merchant_id": 101, "customer_enterprise_id": 11})
        c.post("/demands", json={"demand_id": 1001, "enterprise_id": 11, "category": "螺纹",
                                 "spec": "HRB400E Φ20", "quantity": 100,
                                 "delivery_region": "华北", "target_price": 3850})
        c.post("/demands", json={"demand_id": 1002, "enterprise_id": 12, "category": "螺纹",
                                 "spec": "HRB400E Φ20", "quantity": 50,
                                 "delivery_region": "华北", "target_price": 3850,
                                 "is_public": True})
        c.post("/listings", json={"listing_id": 2001, "merchant_id": 102, "category": "螺纹",
                                  "spec": "HRB400E Φ20", "quantity": 500, "price": 3820,
                                  "warehouse_region": "华北", "visibility": "public"})

    def test_health(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")

    def test_matching_excludes_strategic_via_api(self):
        self._seed()
        r = self.client.post("/match/listing/2001")
        ids = {m["buyer_enterprise_id"] for m in r.json()}
        self.assertNotIn(11, ids)  # 战略客户不被撮合
        self.assertIn(12, ids)

    def test_gateway_blocks_via_api(self):
        self._seed()
        denied = self.client.get("/gateway/access",
                                 params={"actor_merchant_id": 102, "customer_id": 11}).json()
        self.assertFalse(denied["allowed"])
        allowed = self.client.get("/gateway/access",
                                  params={"actor_merchant_id": 101, "customer_id": 11}).json()
        self.assertTrue(allowed["allowed"])

    def test_strategic_conflict_409(self):
        self._seed()
        r = self.client.post("/relations/strategic",
                             json={"merchant_id": 102, "customer_enterprise_id": 11})
        self.assertEqual(r.status_code, 409)

    def test_credit_terms(self):
        r = self.client.post("/credit/terms", json={"enterprise_id": 11,
                             "repayment_on_time": 0.98, "fulfillment_rate": 0.97,
                             "years_in_business": 8, "order_amount": 100000})
        body = r.json()
        self.assertEqual(body["tier"], "A")
        self.assertGreater(body["account_period_days"], 0)

    def test_pricelock_flow(self):
        r = self.client.post("/pricelock", json={"buyer_enterprise_id": 11, "listing_id": 2001,
                             "price": 3820, "quantity": 100, "duration_hours": 6})
        lock_id = r.json()["lock_id"]
        ex = self.client.post(f"/pricelock/{lock_id}/exercise")
        self.assertEqual(ex.json()["status"], "exercised")

    def test_pricelock_volatility_rejected(self):
        r = self.client.post("/pricelock", json={"buyer_enterprise_id": 11, "listing_id": 2001,
                             "price": 3820, "quantity": 100, "duration_hours": 24,
                             "volatility": 0.06})
        self.assertEqual(r.status_code, 400)

    def test_recovery_price_blocker(self):
        r = self.client.post("/recovery/plan", json={"buyer_enterprise_id": 11,
                             "quoted_price": 3950, "market_avg_price": 3820,
                             "buyer_hist_avg_price": 3800, "hours_since_inquiry": 25})
        self.assertEqual(r.json()["blocker"], "price_too_high")


if __name__ == "__main__":
    unittest.main()
