"""Step 1: load the Chainlink BTC/USD price and TWAP60 files the backtest runs on.

The files come from Poly Tick Tape (https://polyticktape.com/?ref=bt), one per UTC
day and stream, named btc-price-YYYY-MM-DD.jsonl.gz and btc-twap60-YYYY-MM-DD.jsonl.gz.
Every line is one second:

  {"ts":1789878900,"p":"80413.342489811802390528","v":80413.3424898118,"lag":1568,
   "feed_ts_ms":1789878900000,"server_ts_ms":1789878901244,"recv_ms":1789878901568}

Two things the backtest takes from them:
  - the price to beat (TWAP60 at a round's start second) and the TWAP60 at its end
    second, compared exactly as decimals, the way Polymarket settles;
  - the BTC value a trader could actually see at a given second: the newest row whose
    recv_ms had arrived by then, so no signal ever uses a value from the future.
"""

import bisect
import gzip
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from array import array
from datetime import date, datetime, timedelta, timezone

API = "https://polyticktape.com"
BUY_URL = "https://polyticktape.com/pricing/?ref=bt"
STREAMS = ("twap60", "price")
ROUND = 300
DAY = 86400
FILE_RE = re.compile(r"^btc-(price|twap60)-(\d{4}-\d{2}-\d{2})(?:T(\d{2}))?\.jsonl\.gz$")
# The published files keep this field order; json.loads is the fallback when they don't.
LINE_RE = re.compile(rb'\{"ts":(\d+),"p":"([^"]+)","v":([^,]+),.*?"recv_ms":(\d+)\}')


class DataMissing(Exception):
    """Raised when the Chainlink files for the requested days aren't there."""

    def __init__(self, message, missing=(), hint=None, code="no_data"):
        super().__init__(message)
        self.message = message
        self.missing = list(missing)
        self.hint = hint
        self.code = code

    def to_dict(self):
        return {"code": self.code, "message": self.message, "missing": self.missing,
                "hint": self.hint, "buyUrl": BUY_URL}


def day_start(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def utc_date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).date()


def scan(data_dir):
    """Finds Chainlink files under data_dir. Returns {(stream, key): path}.

    key is "YYYY-MM-DD" for a day file and "YYYY-MM-DDTHH" for an hour file (the free sample).
    """
    found = {}
    if not os.path.isdir(data_dir):
        return found
    for root, _dirs, files in os.walk(data_dir):
        for name in files:
            m = FILE_RE.match(name)
            if m:
                key = m.group(2) + (f"T{m.group(3)}" if m.group(3) else "")
                found[(m.group(1), key)] = os.path.join(root, name)
    return found


def available(data_dir):
    """Days (or sample hours) that have both streams, sorted."""
    files = scan(data_dir)
    keys = {k for (_s, k) in files}
    return sorted(k for k in keys if all((s, k) in files for s in STREAMS))


def span_of(key):
    """[start, end) in Unix seconds covered by a file key."""
    d = date.fromisoformat(key[:10])
    start = day_start(d)
    if "T" in key:
        start += int(key[11:13]) * 3600
        return start, start + 3600
    return start, start + DAY


class Stream:
    """One stream over the loaded range: rows sorted by ts, plus exact values at round boundaries."""

    def __init__(self):
        self.ts = array("q")
        self.recv = array("q")
        self.v = array("d")
        self.exact = {}  # ts -> full-precision string, only for seconds divisible by 300

    def add_file(self, path):
        with gzip.open(path, "rb") as f:
            body = f.read()
        rows = LINE_RE.findall(body)
        if len(rows) != body.count(b"\n"):
            rows = []
            for line in body.splitlines():
                if line.strip():
                    o = json.loads(line)
                    rows.append((o["ts"], o["p"], o["v"], o["recv_ms"]))
        last = self.ts[-1] if self.ts else -1
        for ts, p, v, recv in rows:
            ts = int(ts)
            if ts <= last:  # overlapping files (a sample hour next to its day): keep the first copy
                continue
            last = ts
            self.ts.append(ts)
            self.recv.append(int(recv))
            self.v.append(float(v))
            if ts % ROUND == 0:
                self.exact[ts] = p.decode() if isinstance(p, bytes) else p

    def row_index(self, ts):
        i = bisect.bisect_left(self.ts, ts)
        return i if i < len(self.ts) and self.ts[i] == ts else -1

    def seen_at(self, t, max_age=10):
        """The newest value that had arrived by second t (recv_ms <= t*1000), or None.

        Rows usually arrive 1.5-3 s after their own second. A value older than max_age
        seconds counts as missing rather than being carried forward.
        """
        i = bisect.bisect_right(self.ts, t) - 1
        limit = t * 1000
        while i >= 0 and self.recv[i] > limit:
            i -= 1
        if i < 0 or t - self.ts[i] > max_age:
            return None
        return self.v[i]

    def arrived_by(self, ts, t):
        """True when the row for second ts exists and had arrived by second t."""
        i = self.row_index(ts)
        return i >= 0 and self.recv[i] <= t * 1000


class Chainlink:
    def __init__(self, keys, spans, streams):
        self.keys = keys
        self.spans = spans
        self.twap60 = streams["twap60"]
        self.price = streams["price"]

    def round_starts(self):
        """Every round that starts and ends inside the requested spans (the 23:55 round ends at 00:00)."""
        return [s for a, b in self.spans for s in range(a, b - ROUND + 1, ROUND)]


def load(data_dir, date_from=None, date_to=None, keys=None):
    """Loads both streams for the given UTC days. Raises DataMissing if any file is absent.

    Pass keys to load specific file keys instead (used for the sample hour). The day after
    date_to is loaded too when present, so the 23:55 round can be settled at 00:00:00.
    """
    files = scan(data_dir)
    if keys is None:
        if not date_from or not date_to:
            raise DataMissing("Pick a date range.", code="bad_range")
        d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
        if d1 < d0:
            raise DataMissing("The end date is before the start date.", code="bad_range")
        keys = [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]
    if not files:
        raise DataMissing(
            f"No Chainlink data files found in {os.path.abspath(data_dir)}.",
            missing=keys,
            hint="This backtest needs per-second Chainlink BTC/USD price and TWAP60 files. "
                 "Buy them at polyticktape.com, or try the free sample hour first.")
    missing = [f"btc-{s}-{k}.jsonl.gz" for k in keys for s in STREAMS if (s, k) not in files]
    if missing:
        raise DataMissing(
            f"{len(missing)} file(s) missing for {keys[0]} to {keys[-1]}.",
            missing=missing,
            hint="Download them with your API key, or buy the period that covers these days.")
    load_keys = list(keys)
    if "T" not in keys[-1]:
        nxt = (date.fromisoformat(keys[-1]) + timedelta(days=1)).isoformat()
        if all((s, nxt) in files for s in STREAMS):
            load_keys.append(nxt)
    streams = {}
    for s in STREAMS:
        st = Stream()
        for k in sorted(load_keys):
            st.add_file(files[(s, k)])
        streams[s] = st
    return Chainlink(keys, merge_spans(span_of(k) for k in keys), streams)


def merge_spans(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def download(key, date_from, date_to, out_dir, progress=None):
    """Downloads the day files for [date_from, date_to] with an API key and checks each SHA-256.

    Files already in out_dir with the right checksum are skipped, so a re-run doesn't spend
    download quota twice. Raises DataMissing with the API's code and hint on 401/403.
    """
    q = f"from={date_from}&to={date_to}&streams=price,twap60"
    listing = _api_json(f"{API}/v1/days?{q}", key)
    files = [day[s] for day in listing["days"] for s in listing["streams"] if s in day]
    os.makedirs(out_dir, exist_ok=True)
    saved = 0
    for i, f in enumerate(files):
        path = os.path.join(out_dir, f["name"])
        if progress:
            progress(i, len(files), f["name"])
        if os.path.exists(path) and _sha256(path) == f["sha256"]:
            continue
        req = urllib.request.Request(f["url"], headers={"Authorization": f"Bearer {key}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
        if hashlib.sha256(body).hexdigest() != f["sha256"]:
            raise DataMissing(f"Checksum mismatch for {f['name']}. Run the download again.", code="checksum")
        with open(path, "wb") as out:
            out.write(body)
        saved += 1
    if progress:
        progress(len(files), len(files), "")
    not_entitled = [f"{m['date']} {m['stream']}" for m in listing.get("missing", []) if m["reason"] == "not_entitled"]
    return {"files": len(files), "saved": saved, "missing": listing.get("missing", []), "notEntitled": not_entitled}


UA = "polymarket-btc-5m-backtest/1.0"


def _api_json(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except ValueError:
            err = {}
        raise DataMissing(err.get("message") or f"HTTP {e.code} from the data API.",
                          hint=err.get("hint"), code=err.get("code") or f"http_{e.code}") from None
    except urllib.error.URLError as e:
        raise DataMissing(f"Couldn't reach {API}: {e.reason}", code="network") from None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
