"""Step 3: replay a three-condition strategy over every round and score it.

For each 5-minute round the engine walks the second-by-second taker BUY prints in order
and buys on the first one where all three conditions hold:

  1. odds    the side you buy (the favorite or the underdog) costs between prob_min and prob_max
  2. move    BTC (as seen at that second) minus the price to beat, measured toward the side
             you buy, is between move_min and move_max dollars
  3. time    the print is between elapsed_min and elapsed_max seconds into the round

One trade per round at most. The fill is the print's price plus slippage ticks, and the
fee is Polymarket's taker fee: shares x 0.07 x p x (1 - p). A winning share pays $1.
"""

from decimal import Decimal

ROUND = 300
FEE_RATE = 0.07
MAX_ENTRY = 0.99
UP, DOWN = 0, 1
SIDES = ("Up", "Down")

DEFAULTS = {
    "side": "favorite",     # favorite | underdog
    "prob_min": 0.80,
    "prob_max": 0.95,
    "move_mode": "with",    # with = BTC moved toward the side you buy | against | any
    "move_min": 20.0,       # USD
    "move_max": 0.0,        # USD, 0 = no limit
    "btc_source": "twap60",  # twap60 | price
    "elapsed_min": 180,
    "elapsed_max": 285,
    "stake": 10.0,          # USD per trade
    "slippage_ticks": 1,
}

REASONS = ("noChainlink", "noOdds", "time", "odds", "move", "btcData", "tooExpensive")


def normalize(params):
    p = dict(DEFAULTS)
    for k, v in (params or {}).items():
        if k in DEFAULTS and v not in (None, ""):
            p[k] = v if isinstance(DEFAULTS[k], str) else type(DEFAULTS[k])(float(v))
    if p["side"] not in ("favorite", "underdog"):
        raise ValueError("side must be favorite or underdog")
    if p["move_mode"] not in ("with", "against", "any"):
        raise ValueError("move_mode must be with, against or any")
    if p["btc_source"] not in ("twap60", "price"):
        raise ValueError("btc_source must be twap60 or price")
    if not 0 <= p["prob_min"] <= p["prob_max"] <= 1:
        raise ValueError("odds range must satisfy 0 <= min <= max <= 1")
    if not 0 <= p["elapsed_min"] <= p["elapsed_max"] < ROUND:
        raise ValueError("window time must satisfy 0 <= min <= max < 300")
    if p["move_min"] < 0 or p["move_max"] < 0:
        raise ValueError("BTC move limits can't be negative")
    if p["stake"] <= 0:
        raise ValueError("stake must be positive")
    return p


def tick_size(price):
    return 0.001 if price < 0.04 or price > 0.96 else 0.01


def run(params, chain, rounds, starts):
    """chain: chainlink.Chainlink, rounds: odds.load() output, starts: round start seconds."""
    p = normalize(params)
    btc = chain.twap60 if p["btc_source"] == "twap60" else chain.price
    favorite = p["side"] == "favorite"
    trades, skipped = [], dict.fromkeys(REASONS, 0)
    checked = agree = 0
    disagree = []

    for s in starts:
        start_p, end_p = chain.twap60.exact.get(s), chain.twap60.exact.get(s + ROUND)
        odds = rounds.get(s)
        official = odds["winner"] if odds else None
        twap_winner = None
        if start_p is not None and end_p is not None:
            twap_winner = "Up" if Decimal(end_p) >= Decimal(start_p) else "Down"
            if official:
                checked += 1
                if official == twap_winner:
                    agree += 1
                else:
                    disagree.append(s)
        if start_p is None:
            skipped["noChainlink"] += 1
            continue
        winner = official or twap_winner
        if not odds or not odds["buys"] or winner is None:
            skipped["noOdds"] += 1
            continue
        strike = float(start_p)

        block, trade = "time", None
        for sec, side, price in odds["buys"]:
            if sec < p["elapsed_min"]:
                continue
            if sec > p["elapsed_max"]:
                break
            up_prob = price if side == UP else 1 - price
            want = UP if (up_prob >= 0.5) == favorite else DOWN  # at exactly 0.5 Up counts as the favorite
            if side != want or not p["prob_min"] <= price <= p["prob_max"]:
                block = "odds"
                continue
            t = s + sec
            seen = btc.seen_at(t)
            if seen is None or not chain.twap60.arrived_by(s, t):
                block = "btcData"
                continue
            move = seen - strike
            toward = move if side == UP else -move
            size = {"with": toward, "against": -toward, "any": abs(move)}[p["move_mode"]]
            if size < p["move_min"] or (p["move_max"] > 0 and size > p["move_max"]):
                block = "move"
                continue
            tick = tick_size(price)
            fill = min(1 - tick, price + p["slippage_ticks"] * tick)
            if fill >= MAX_ENTRY:
                block = "tooExpensive"
                continue
            shares = p["stake"] / fill
            fee = shares * FEE_RATE * fill * (1 - fill) if odds["fee"] else 0.0
            won = SIDES[side] == winner
            trade = {
                "round": s, "ts": t, "elapsed": sec, "side": SIDES[side], "prob": price,
                "move": round(move, 2), "fill": round(fill, 4), "shares": round(shares, 4),
                "fee": round(fee, 4), "won": won,
                "pnl": round((shares if won else 0) - p["stake"] - fee, 4),
            }
            break
        if trade:
            trades.append(trade)
        else:
            skipped[block] += 1

    return {"params": p, "summary": summarize(trades, p["stake"], len(starts)), "skipped": skipped,
            "settlement": {"checked": checked, "agree": agree, "disagree": disagree},
            "trades": trades}


def summarize(trades, stake, n_rounds):
    n = len(trades)
    wins = sum(t["won"] for t in trades)
    pnl = sum(t["pnl"] for t in trades)
    fees = sum(t["fee"] for t in trades)
    equity = peak = drawdown = 0.0
    for t in trades:
        equity += t["pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "rounds": n_rounds,
        "trades": n,
        "wins": wins,
        "winRate": wins / n if n else None,
        # what a share cost on average, fee included. A winning share pays $1, so with a narrow
        # price band the win rate has to beat this number to make money
        "avgCost": sum(t["fill"] + t["fee"] / t["shares"] for t in trades) / n if n else None,
        "pnl": round(pnl, 2),
        "staked": round(n * stake, 2),
        "roi": pnl / (n * stake) if n else None,
        "fees": round(fees, 2),
        "maxDrawdown": round(drawdown, 2),
    }
