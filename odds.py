"""Step 2: the market's odds for each round, from Polymarket's free public APIs.

  Gamma API  /markets?slug=btc-updown-5m-<start>   condition id, resolved outcome, fee flag
  Data API   /trades?market=<condition id>          every taker trade, to the second

Only taker BUY trades are kept: a taker buying Up at 0.83 is a price you could have
bought Up at in that second. For each second and side the highest such price is kept,
the conservative end. Results are cached per UTC day in cache/odds-YYYY-MM-DD.json.gz,
so each round is fetched once. No API key is needed.
"""

import gzip
import http.client
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

GAMMA = "gamma-api.polymarket.com"
DATA = "data-api.polymarket.com"
ROUND = 300
PAGE = 1000
MAX_OFFSET = 10000  # the Data API's public offset limit
UA = "polymarket-btc-5m-backtest/1.0"
UP, DOWN = 0, 1
CACHE_VERSION = 1

_local = threading.local()


def _get(host, path, tries=5):
    """GET https://host/path as JSON over a kept-alive connection per thread."""
    for attempt in range(tries):
        conns = getattr(_local, "conns", None)
        if conns is None:
            conns = _local.conns = {}
        conn = conns.get(host)
        if conn is None:
            conn = conns[host] = http.client.HTTPSConnection(host, timeout=60)
        try:
            conn.request("GET", path, headers={"User-Agent": UA, "Accept": "application/json"})
            r = conn.getresponse()
            body = r.read()
            if r.status == 429 or r.status >= 500:
                time.sleep(min(8, 0.5 * 2 ** attempt))
                continue
            if r.status == 404:
                return None
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status} from https://{host}{path[:80]}")
            return json.loads(body)
        except (OSError, http.client.HTTPException, ValueError):
            conn.close()
            conns.pop(host, None)
            if attempt == tries - 1:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError(f"https://{host} kept failing; try again in a minute")


def fetch_markets(starts):
    """Gamma metadata for up to 50 rounds per request: {start: {cid, winner, fee}}."""
    out = {}
    for i in range(0, len(starts), 50):
        chunk = starts[i:i + 50]
        q = "&".join(f"slug=btc-updown-5m-{s}" for s in chunk)
        for m in _get(GAMMA, f"/markets?closed=true&limit=100&{q}") or []:
            s = int(m["slug"].rsplit("-", 1)[1])
            try:
                outcomes = json.loads(m.get("outcomes") or "[]")
                prices = json.loads(m.get("outcomePrices") or "[]")
            except ValueError:
                outcomes, prices = [], []
            winner = None
            if len(outcomes) == 2 and len(prices) == 2:
                winner = outcomes[0] if prices[0] == "1" else outcomes[1] if prices[1] == "1" else None
            out[s] = {"cid": m.get("conditionId"), "winner": winner, "fee": m.get("feesEnabled") is not False}
    return out


def fetch_buys(cid, start):
    """Taker BUYs inside [start, start+300): [[second, side, price], ...], highest price per second and side."""
    best = {}
    for off in range(0, MAX_OFFSET + 1, PAGE):
        page = _get(DATA, f"/trades?market={cid}&takerOnly=true&side=BUY&limit={PAGE}&offset={off}"
                          f"&start={start}&end={start + ROUND}")
        if not page:
            break
        for t in page:
            sec = int(t["timestamp"]) - start
            if t.get("side") != "BUY" or not 0 <= sec < ROUND:
                continue
            side = UP if t.get("outcome") == "Up" else DOWN
            price = float(t["price"])
            if price > best.get((sec, side), 0):
                best[(sec, side)] = price
        if len(page) < PAGE:
            break
    return [[sec, side, round(p, 6)] for (sec, side), p in sorted(best.items())]


def _cache_path(cache_dir, day):
    return os.path.join(cache_dir, f"odds-{day}.json.gz")


def _read_cache(path):
    try:
        with gzip.open(path, "rt") as f:
            d = json.load(f)
        if d.get("version") == CACHE_VERSION:
            return {int(k): v for k, v in d["rounds"].items()}
    except (OSError, ValueError, KeyError):
        pass
    return {}


def _write_cache(path, rounds):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt") as f:
        json.dump({"version": CACHE_VERSION, "rounds": {str(k): v for k, v in sorted(rounds.items())}}, f,
                  separators=(",", ":"))
    os.replace(tmp, path)


def load(starts, cache_dirs, progress=None, workers=8, fetch=True):
    """Odds for each round start: {start: {"winner": "Up"|"Down"|None, "fee": bool, "buys": [...]}}.

    cache_dirs[0] is where new rounds are written; later entries are read-only (the bundled
    sample). Rounds Polymarket hasn't resolved yet are fetched but not cached.
    """
    by_day = {}
    for s in starts:
        by_day.setdefault(datetime.fromtimestamp(s, timezone.utc).date().isoformat(), []).append(s)
    result, todo = {}, []
    for day, day_starts in sorted(by_day.items()):
        cached = {}
        for d in reversed(cache_dirs):
            cached.update(_read_cache(_cache_path(d, day)))
        for s in day_starts:
            if s in cached:
                result[s] = cached[s]
            else:
                todo.append(s)
    total, done = len(starts), len(starts) - len(todo)
    if progress:
        progress(done, total)
    if not todo or not fetch:
        return result

    now = time.time()
    lock = threading.Lock()
    fetched = {}

    def one(s, meta):
        nonlocal done
        rec = None
        if meta and meta["cid"]:
            rec = {"winner": meta["winner"], "fee": meta["fee"], "buys": fetch_buys(meta["cid"], s)}
        with lock:
            fetched[s] = rec
            done += 1
            if progress:
                progress(done, total)

    with ThreadPoolExecutor(workers) as pool:
        for i in range(0, len(todo), 288):  # one day's worth at a time, then write its cache
            chunk = todo[i:i + 288]
            metas = fetch_markets(chunk)
            list(pool.map(lambda s: one(s, metas.get(s)), chunk))
            _save(chunk, fetched, cache_dirs[0], now)
    result.update(fetched)
    return result


def _save(chunk, fetched, cache_dir, now):
    days = {}
    for s in chunk:
        rec = fetched.get(s)
        settled = rec is not None and rec["winner"] is not None
        gone = rec is None and s + ROUND < now - 86400  # no market for this round, and it's long past
        if settled or gone:
            days.setdefault(datetime.fromtimestamp(s, timezone.utc).date().isoformat(), {})[s] = rec
    for day, rounds in days.items():
        path = _cache_path(cache_dir, day)
        merged = _read_cache(path)
        merged.update(rounds)
        _write_cache(path, merged)
