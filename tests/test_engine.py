"""python -m unittest  (from the repository root)"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backtest  # noqa: E402
import chainlink  # noqa: E402
import engine  # noqa: E402
import odds  # noqa: E402

S = 1789876800  # a round start


def stream(rows):
    """rows: [(ts, value, lag_ms)]"""
    st = chainlink.Stream()
    for ts, v, lag in rows:
        st.ts.append(ts)
        st.recv.append(ts * 1000 + lag)
        st.v.append(v)
        if ts % 300 == 0:
            st.exact[ts] = repr(v)
    return st


def chain(values, lag=2000):
    """TWAP60 = price = values[sec] for each second of one round plus its end second."""
    rows = [(S + i, v, lag) for i, v in enumerate(values)]
    st = stream(rows)
    c = chainlink.Chainlink(["x"], [(S, S + 300)], {"twap60": st, "price": st})
    return c


def flat_then(move, at=1):
    """Strike 100000, BTC moves by `move` from second `at` and stays there through the end."""
    return [100000.0] * at + [100000.0 + move] * (301 - at)


class SeenAt(unittest.TestCase):
    def test_uses_only_rows_that_have_arrived(self):
        st = stream([(S, 1.0, 2500), (S + 1, 2.0, 2500), (S + 2, 3.0, 2500)])
        self.assertIsNone(st.seen_at(S + 2))  # row S arrives at S+2.5
        self.assertEqual(st.seen_at(S + 3), 1.0)
        self.assertEqual(st.seen_at(S + 5), 3.0)

    def test_stale_value_counts_as_missing(self):
        st = stream([(S, 1.0, 0)])
        self.assertEqual(st.seen_at(S + 10), 1.0)
        self.assertIsNone(st.seen_at(S + 11))


class Engine(unittest.TestCase):
    def rounds(self, buys, winner="Up", fee=True):
        return {S: {"winner": winner, "fee": fee, "buys": buys}}

    def run_one(self, params, buys, values, winner="Up", fee=True):
        return engine.run(params, chain(values), self.rounds(buys, winner, fee), [S])

    def test_buys_first_qualifying_print_and_charges_fee(self):
        p = {"prob_min": 0.8, "prob_max": 0.95, "move_min": 20, "elapsed_min": 180, "elapsed_max": 285}
        buys = [[170, 0, 0.85], [200, 0, 0.70], [210, 0, 0.88], [220, 0, 0.90]]
        r = self.run_one(p, buys, flat_then(30))
        self.assertEqual(len(r["trades"]), 1)
        t = r["trades"][0]
        self.assertEqual((t["elapsed"], t["side"], t["fill"]), (210, "Up", 0.89))
        shares = 10 / 0.89
        self.assertAlmostEqual(t["fee"], round(shares * 0.07 * 0.89 * 0.11, 4))
        self.assertAlmostEqual(t["pnl"], round(shares - 10 - shares * 0.07 * 0.89 * 0.11, 4))

    def test_down_side_needs_btc_below_strike(self):
        p = {"prob_min": 0.8, "prob_max": 0.95, "move_min": 20, "elapsed_min": 0, "elapsed_max": 299}
        buys = [[100, 1, 0.9]]  # a Down print at 0.90: Down is the favorite
        self.assertEqual(self.run_one(p, buys, flat_then(30), "Down")["trades"], [])
        r = self.run_one(p, buys, flat_then(-30), "Down")
        self.assertTrue(r["trades"][0]["won"])

    def test_move_modes(self):
        base = {"prob_min": 0.5, "prob_max": 0.99, "move_min": 20, "elapsed_min": 0, "elapsed_max": 299}
        buys = [[100, 0, 0.6]]
        against = flat_then(-25)
        self.assertEqual(self.run_one({**base, "move_mode": "with"}, buys, against)["trades"], [])
        self.assertEqual(len(self.run_one({**base, "move_mode": "against"}, buys, against)["trades"]), 1)
        self.assertEqual(len(self.run_one({**base, "move_mode": "any"}, buys, against)["trades"]), 1)
        capped = {**base, "move_mode": "any", "move_max": 24}
        self.assertEqual(self.run_one(capped, buys, against)["trades"], [])

    def test_underdog_buys_the_cheaper_side_only(self):
        p = {"side": "underdog", "prob_min": 0.05, "prob_max": 0.3, "move_mode": "any", "move_min": 0,
             "elapsed_min": 0, "elapsed_max": 299}
        buys = [[50, 0, 0.8], [60, 1, 0.2]]
        r = self.run_one(p, buys, flat_then(10), "Up")
        self.assertEqual([(t["side"], t["won"]) for t in r["trades"]], [("Down", False)])

    def test_btc_not_yet_seen_blocks(self):
        p = {"prob_min": 0.5, "prob_max": 0.99, "move_mode": "any", "move_min": 0, "elapsed_min": 0, "elapsed_max": 299}
        # the start second's row arrives 3 s late, so at second 1 nobody knows the price to beat yet
        r = engine.run(p, chain(flat_then(0), lag=3000), self.rounds([[1, 0, 0.6]]), [S])
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["skipped"]["btcData"], 1)

    def test_too_expensive_and_fee_free(self):
        p = {"prob_min": 0.9, "prob_max": 1, "move_mode": "any", "move_min": 0, "elapsed_min": 0, "elapsed_max": 299}
        # 0.99 + one 0.001 tick is past the 0.99 cap; 0.97 + 0.001 fills
        r = self.run_one(p, [[100, 0, 0.99], [101, 0, 0.97]], flat_then(50), fee=False)
        t = r["trades"][0]
        self.assertEqual((t["elapsed"], t["fill"], t["fee"]), (101, 0.971, 0.0))

    def test_settlement_check_uses_exact_twap(self):
        r = self.run_one({}, [], flat_then(5), winner="Up")
        self.assertEqual(r["settlement"], {"checked": 1, "agree": 1, "disagree": []})


class Sample(unittest.TestCase):
    def test_sample_hour_runs_offline_and_matches_polymarket(self):
        pipe = backtest.Pipeline(tempfile.mkdtemp(), tempfile.mkdtemp())
        res = pipe.run({}, None, None, True, lambda *a: None)
        self.assertEqual(res["summary"]["rounds"], 12)
        self.assertEqual(res["settlement"], {"checked": 12, "agree": 12, "disagree": []})
        self.assertEqual(res["summary"]["trades"], 9)

    def test_empty_data_dir_asks_to_buy(self):
        with self.assertRaises(chainlink.DataMissing) as cm:
            chainlink.load(tempfile.mkdtemp(), "2026-09-01", "2026-09-02")
        self.assertEqual(cm.exception.code, "no_data")
        self.assertIn("polyticktape.com", cm.exception.to_dict()["buyUrl"])

    def test_missing_day_is_listed(self):
        d = tempfile.mkdtemp()
        for s in ("price", "twap60"):
            open(os.path.join(d, f"btc-{s}-2026-09-01.jsonl.gz"), "wb").close()
        with self.assertRaises(chainlink.DataMissing) as cm:
            chainlink.load(d, "2026-09-01", "2026-09-02")
        self.assertEqual(cm.exception.missing, ["btc-twap60-2026-09-02.jsonl.gz", "btc-price-2026-09-02.jsonl.gz"])

    def test_cache_round_trip(self):
        d = tempfile.mkdtemp()
        rounds = {S: {"winner": "Up", "fee": True, "buys": [[1, 0, 0.5]]}}
        odds._write_cache(os.path.join(d, "odds-2026-09-20.json.gz"), rounds)
        self.assertEqual(odds.load([S], [d], fetch=False), rounds)


if __name__ == "__main__":
    unittest.main()
