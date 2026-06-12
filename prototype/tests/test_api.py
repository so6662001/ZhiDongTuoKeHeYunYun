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
        self.tok_a = None
        self.tok_b = None

    def _h(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _seed(self):
        c = self.client
        self.tok_a = c.post("/merchants", json={"merchant_id": 101, "enterprise_id": 1}).json()["token"]
        self.tok_b = c.post("/merchants", json={"merchant_id": 102, "enterprise_id": 2}).json()["token"]
        c.post("/enterprises", json={"enterprise_id": 11, "name": "C1", "ent_type": "end_user",
                                     "region_code": "华北", "main_categories": ["螺纹"]})
        c.post("/enterprises", json={"enterprise_id": 12, "name": "C2", "ent_type": "retailer",
                                     "region_code": "华北", "main_categories": ["螺纹"]})
        c.post("/relations", json={"customer_enterprise_id": 11, "relation_type": "dealt"},
               headers=self._h(self.tok_a))
        c.post("/relations/strategic", json={"customer_enterprise_id": 11},
               headers=self._h(self.tok_a))
        c.post("/demands", json={"demand_id": 1001, "enterprise_id": 11, "category": "螺纹",
                                 "spec": "HRB400E Φ20", "quantity": 100,
                                 "delivery_region": "华北", "target_price": 3850})
        c.post("/demands", json={"demand_id": 1002, "enterprise_id": 12, "category": "螺纹",
                                 "spec": "HRB400E Φ20", "quantity": 50, "delivery_region": "华北",
                                 "target_price": 3850, "is_public": True})
        c.post("/listings", json={"listing_id": 2001, "merchant_id": 102, "category": "螺纹",
                                  "spec": "HRB400E Φ20", "quantity": 500, "price": 3820,
                                  "warehouse_region": "华北", "visibility": "public"},
               headers=self._h(self.tok_b))

    def test_health(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")

    def test_requires_auth(self):
        # 无令牌访问受保护接口 -> 401
        self.assertEqual(self.client.get("/gateway/access",
                         params={"customer_id": 11}).status_code, 401)

    def test_invalid_token(self):
        r = self.client.get("/gateway/access", params={"customer_id": 11},
                            headers=self._h("bogus"))
        self.assertEqual(r.status_code, 401)

    def test_matching_excludes_strategic_via_api(self):
        self._seed()
        r = self.client.post("/match/listing/2001", headers=self._h(self.tok_b))
        ids = {m["buyer_enterprise_id"] for m in r.json()}
        self.assertNotIn(11, ids)  # 战略客户不被撮合
        self.assertIn(12, ids)

    def test_gateway_blocks_via_api(self):
        self._seed()
        denied = self.client.get("/gateway/access", params={"customer_id": 11},
                                 headers=self._h(self.tok_b)).json()
        self.assertFalse(denied["allowed"])  # B 看不到 A 的战略客户
        allowed = self.client.get("/gateway/access", params={"customer_id": 11},
                                  headers=self._h(self.tok_a)).json()
        self.assertTrue(allowed["allowed"])  # A 看自己的客户

    def test_cannot_match_others_listing(self):
        self._seed()
        # A 试图为 B 的货源做撮合 -> 403
        r = self.client.post("/match/listing/2001", headers=self._h(self.tok_a))
        self.assertEqual(r.status_code, 403)

    def test_cannot_create_listing_as_other_merchant(self):
        self._seed()
        r = self.client.post("/listings", json={"listing_id": 2099, "merchant_id": 999,
                             "category": "螺纹", "spec": "x", "quantity": 1, "price": 1,
                             "warehouse_region": "华北"}, headers=self._h(self.tok_a))
        self.assertEqual(r.status_code, 403)

    def test_strategic_conflict_409(self):
        self._seed()
        r = self.client.post("/relations/strategic", json={"customer_enterprise_id": 11},
                             headers=self._h(self.tok_b))
        self.assertEqual(r.status_code, 409)

    def test_my_customers_scoped(self):
        self._seed()
        a_list = self.client.get("/my/customers", headers=self._h(self.tok_a)).json()
        self.assertEqual({c["customer_enterprise_id"] for c in a_list}, {11})
        b_list = self.client.get("/my/customers", headers=self._h(self.tok_b)).json()
        self.assertEqual(b_list, [])

    def test_credit_terms(self):
        self._seed()
        r = self.client.post("/credit/terms", json={"enterprise_id": 11, "repayment_on_time": 0.98,
                             "fulfillment_rate": 0.97, "years_in_business": 8,
                             "order_amount": 100000}, headers=self._h(self.tok_a))
        self.assertEqual(r.json()["tier"], "A")

    def test_pricelock_flow(self):
        self._seed()
        r = self.client.post("/pricelock", json={"buyer_enterprise_id": 11, "listing_id": 2001,
                             "price": 3820, "quantity": 100, "duration_hours": 6},
                             headers=self._h(self.tok_a))
        lock_id = r.json()["lock_id"]
        ex = self.client.post(f"/pricelock/{lock_id}/exercise", headers=self._h(self.tok_a))
        self.assertEqual(ex.json()["status"], "exercised")

    def test_recovery_price_blocker(self):
        self._seed()
        r = self.client.post("/recovery/plan", json={"buyer_enterprise_id": 11,
                             "quoted_price": 3950, "market_avg_price": 3820,
                             "buyer_hist_avg_price": 3800, "hours_since_inquiry": 25},
                             headers=self._h(self.tok_a))
        self.assertEqual(r.json()["blocker"], "price_too_high")


@unittest.skipUnless(HAS_FASTAPI, "fastapi 未安装")
class TestApiPersistence(unittest.TestCase):
    def test_persist_and_reload(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "api.db")
        c1 = TestClient(create_app(db_path=path))
        tok = c1.post("/merchants", json={"merchant_id": 101, "enterprise_id": 1}).json()["token"]
        c1.post("/enterprises", json={"enterprise_id": 11, "name": "C1", "ent_type": "end_user",
                                      "region_code": "华北", "main_categories": ["螺纹"]})
        c1.post("/relations", json={"customer_enterprise_id": 11, "relation_type": "dealt"},
                headers={"Authorization": f"Bearer {tok}"})
        c1.post("/admin/persist", headers={"Authorization": f"Bearer {tok}"})

        # 新进程/新 app 从同一 DB 重载
        c2 = TestClient(create_app(db_path=path))
        tok2 = c2.post("/merchants", json={"merchant_id": 101, "enterprise_id": 1}).json()["token"]
        mine = c2.get("/my/customers", headers={"Authorization": f"Bearer {tok2}"}).json()
        self.assertEqual({m["customer_enterprise_id"] for m in mine}, {11})


if __name__ == "__main__":
    unittest.main()
