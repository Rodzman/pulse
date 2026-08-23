import unittest
from pulse import evaluate


class EvaluateTests(unittest.TestCase):
    def test_healthy(self):
        r = evaluate(name="a", url="http://x", code=200, body="hello world",
                     expect_status=200, keyword="world", max_latency_ms=500, latency_ms=120.0)
        self.assertTrue(r.ok)
        self.assertIsNone(r.error)

    def test_wrong_status(self):
        r = evaluate(name="a", url="http://x", code=503, body="",
                     expect_status=200, keyword=None, max_latency_ms=None, latency_ms=10.0)
        self.assertFalse(r.ok)
        self.assertIn("503", r.error)

    def test_missing_keyword(self):
        r = evaluate(name="a", url="http://x", code=200, body="nothing here",
                     expect_status=200, keyword='"status":"ok"', max_latency_ms=None, latency_ms=10.0)
        self.assertFalse(r.ok)

    def test_too_slow(self):
        r = evaluate(name="a", url="http://x", code=200, body="",
                     expect_status=200, keyword=None, max_latency_ms=100, latency_ms=250.0)
        self.assertFalse(r.ok)
        self.assertIn("latency", r.error)


if __name__ == "__main__":
    unittest.main()