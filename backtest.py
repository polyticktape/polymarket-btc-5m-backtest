#!/usr/bin/env python3
"""Polymarket BTC 5-minute Up/Down backtest: three conditions, real Chainlink data.

  python backtest.py                                   open the web UI (http://127.0.0.1:8765)
  python backtest.py run --sample                      backtest the free sample hour in the terminal
  python backtest.py run --from 2026-09-01 --to 2026-09-30 --prob 0.80-0.95 --move 20 --elapsed 180-285
  python backtest.py download --from 2026-09-01 --to 2026-09-30   (needs POLYTICKTAPE_KEY)

Every run loads data in a fixed order:
  1. Chainlink BTC/USD price + TWAP60 files from ./data (Poly Tick Tape; stops here if missing)
  2. Polymarket odds for each round (free public API, cached in ./cache)
  3. the backtest itself
"""

import argparse
import csv
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chainlink
import engine
import odds

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(HERE, "sample")
SAMPLE_KEY = "2026-09-20T04"
WEB_DIR = os.path.join(HERE, "web")


# ---------------------------------------------------------------- the three steps

class Pipeline:
    """Loads data in order and keeps it in memory, so changing parameters re-runs instantly."""

    def __init__(self, data_dir, cache_dir):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self._chain = (None, None)
        self.rounds = {}

    def chainlink(self, date_from, date_to, sample):
        if sample:
            ident, load = ("sample",), lambda: chainlink.load(SAMPLE_DIR, keys=[SAMPLE_KEY])
        else:
            ident, load = (date_from, date_to), lambda: chainlink.load(self.data_dir, date_from, date_to)
        if self._chain[0] != ident:
            self._chain = (ident, load())
        return self._chain[1]

    def odds(self, starts, progress, sample):
        todo = [s for s in starts if s not in self.rounds]
        if todo:
            dirs = [SAMPLE_DIR] if sample else [self.cache_dir, SAMPLE_DIR]
            self.rounds.update(odds.load(todo, dirs, progress=progress, fetch=not sample))
        progress(len(starts), len(starts))
        return self.rounds

    def run(self, params, date_from, date_to, sample, report):
        report("chainlink", 0, 1)
        chain = self.chainlink(date_from, date_to, sample)
        starts = chain.round_starts()
        report("chainlink", 1, 1)
        rounds = self.odds(starts, lambda d, t: report("odds", d, t), sample)
        report("engine", 0, 1)
        result = engine.run(params, chain, rounds, starts)
        result["range"] = {"from": chain.keys[0], "to": chain.keys[-1], "sample": sample}
        return result


# ---------------------------------------------------------------- web UI

class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"state": "idle"}

    def busy(self):
        return self.state.get("state") in ("running",)

    def update(self, **kw):
        with self.lock:
            self.state.update(kw)

    def start(self, kind, fn):
        with self.lock:
            if self.busy():
                return False
            self.state = {"state": "running", "kind": kind, "step": None, "done": 0, "total": 0}
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()
        return True

    def _run(self, fn):
        try:
            self.update(state="done", result=fn())
        except chainlink.DataMissing as e:
            self.update(state="error", error=e.to_dict())
        except Exception as e:  # shown in the UI rather than lost in the terminal
            self.update(state="error", error={"code": "error", "message": str(e)})


def make_handler(pipe, job):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/status":
                return self.send(200, {
                    "days": [k for k in chainlink.available(pipe.data_dir) if "T" not in k],
                    "dataDir": os.path.abspath(pipe.data_dir),
                    "hasKey": bool(os.environ.get("POLYTICKTAPE_KEY")),
                    "buyUrl": chainlink.BUY_URL,
                    "defaults": engine.DEFAULTS,
                })
            if path == "/api/job":
                with job.lock:
                    return self.send(200, job.state)
            files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path not in files:
                return self.send(404, {"error": "not found"})
            name = files[path]
            ctype = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[name.rsplit(".", 1)[1]]
            with open(os.path.join(WEB_DIR, name), "rb") as f:
                self.send(200, f.read(), ctype + "; charset=utf-8")

        def do_POST(self):
            # the server only listens on 127.0.0.1; this blocks other web pages from posting to it
            if self.headers.get("Content-Type") != "application/json":
                return self.send(415, {"error": "json only"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            report = lambda step, done, total: job.update(step=step, done=done, total=total)
            if self.path == "/api/run":
                fn = lambda: pipe.run(body.get("params"), body.get("from"), body.get("to"),
                                      bool(body.get("sample")), report)
            elif self.path == "/api/download":
                key = (body.get("key") or os.environ.get("POLYTICKTAPE_KEY") or "").strip()
                if not key:
                    return self.send(400, {"error": "API key required"})
                fn = lambda: chainlink.download(key, body.get("from"), body.get("to"), pipe.data_dir,
                                                lambda d, t, _n: report("download", d, t))
            else:
                return self.send(404, {"error": "not found"})
            if not job.start(self.path[5:], fn):
                return self.send(409, {"error": "a job is already running"})
            self.send(202, {"ok": True})

    return Handler


def serve(args):
    pipe = Pipeline(args.data, args.cache)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(pipe, Job()))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Backtest UI: {url}   (Ctrl-C to stop)")
    print(f"Chainlink data folder: {os.path.abspath(args.data)}")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- command line

def span(text, cast=float):
    """'0.8-0.95' -> (0.8, 0.95); '20' -> (20, None)."""
    lo, _, hi = text.partition("-")
    return cast(lo), (cast(hi) if hi else None)


def cli_params(a):
    p = {"side": a.side, "move_mode": a.move_mode, "btc_source": a.btc, "stake": a.stake,
         "slippage_ticks": a.slippage}
    if a.prob:
        p["prob_min"], hi = span(a.prob)
        p["prob_max"] = hi if hi is not None else 1.0
    if a.move:
        p["move_min"], hi = span(a.move)
        p["move_max"] = hi or 0.0
    if a.elapsed:
        p["elapsed_min"], hi = span(a.elapsed, int)
        p["elapsed_max"] = hi if hi is not None else 299
    return p


def fmt_usd(x):
    return f"{'-' if x < 0 else ''}${abs(x):,.2f}"


def fmt_pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def cli_run(a):
    pipe = Pipeline(a.data, a.cache)
    last = {}

    def report(step, done, total):
        if step == "odds" and total and done != last.get("odds") and (done == total or done - last.get("odds", 0) >= 24):
            last["odds"] = done
            print(f"  2/3 Polymarket odds: {done}/{total} rounds", file=sys.stderr)

    print("  1/3 Chainlink data ...", file=sys.stderr)
    try:
        res = pipe.run(cli_params(a), a.date_from, a.date_to, a.sample, report)
    except chainlink.DataMissing as e:
        print(f"\n{e.message}", file=sys.stderr)
        for m in e.missing[:10]:
            print(f"  missing {m}", file=sys.stderr)
        if len(e.missing) > 10:
            print(f"  ... and {len(e.missing) - 10} more", file=sys.stderr)
        if e.hint:
            print(e.hint, file=sys.stderr)
        print(f"\nGet the data: {chainlink.BUY_URL}\nOr try the free sample: python backtest.py run --sample",
              file=sys.stderr)
        return 2
    print("  3/3 backtest done\n", file=sys.stderr)
    s, r = res["summary"], res["range"]
    span = "free sample, 2026-09-20 04:00-05:00" if r["sample"] else f"{r['from']} to {r['to']}"
    print(f"Range        {span} UTC, {s['rounds']} rounds")
    print(f"Trades       {s['trades']}  ({s['wins']} won)")
    print(f"Win rate     {fmt_pct(s['winRate'])}   avg price paid {s['avgCost'] or 0:.3f} incl. fees")
    print(f"Net P&L      {fmt_usd(s['pnl'])} on {fmt_usd(s['staked'])} staked  (ROI {fmt_pct(s['roi'])})")
    print(f"Fees         {fmt_usd(s['fees'])}")
    print(f"Max drawdown {fmt_usd(s['maxDrawdown'])}")
    st = res["settlement"]
    print(f"Settlement   TWAP60 matches Polymarket on {st['agree']}/{st['checked']} rounds")
    print("No trade     " + ", ".join(f"{k} {v}" for k, v in res["skipped"].items() if v))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["round_utc", "slug", "elapsed", "side", "prob", "btc_move", "fill", "shares", "fee", "won", "pnl"])
            for t in res["trades"]:
                w.writerow([datetime.fromtimestamp(t["round"], timezone.utc).strftime("%Y-%m-%d %H:%M"),
                            f"btc-updown-5m-{t['round']}", t["elapsed"], t["side"], t["prob"], t["move"],
                            t["fill"], t["shares"], t["fee"], t["won"], t["pnl"]])
        print(f"\nTrades written to {a.csv}")
    return 0


def cli_download(a):
    key = a.key or os.environ.get("POLYTICKTAPE_KEY")
    if not key:
        print(f"Set POLYTICKTAPE_KEY or pass --key. No key yet? {chainlink.BUY_URL}", file=sys.stderr)
        return 2
    try:
        out = chainlink.download(key, a.date_from, a.date_to, a.data,
                                 lambda d, t, n: n and print(f"  {d + 1}/{t} {n}", file=sys.stderr))
    except chainlink.DataMissing as e:
        print("\n".join(filter(None, [e.message, e.hint, chainlink.BUY_URL])), file=sys.stderr)
        return 2
    print(f"{out['saved']} downloaded, {out['files'] - out['saved']} already here, in {os.path.abspath(a.data)}")
    for m in out["missing"]:
        print(f"  not available: {m['date']} {m['stream']} ({m['reason']})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.path.join(HERE, "data"), help="Chainlink files folder (default ./data)")
    ap.add_argument("--cache", default=os.path.join(HERE, "cache"), help="odds cache folder (default ./cache)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="backtest in the terminal")
    r.add_argument("--from", dest="date_from", help="first UTC day, YYYY-MM-DD")
    r.add_argument("--to", dest="date_to", help="last UTC day, YYYY-MM-DD")
    r.add_argument("--sample", action="store_true", help="use the free sample hour (2026-09-20 04:00-05:00 UTC)")
    r.add_argument("--side", default="favorite", choices=["favorite", "underdog"])
    r.add_argument("--prob", help="price range of the side you buy, e.g. 0.80-0.95")
    r.add_argument("--move", help="BTC move vs price to beat in USD, e.g. 20 or 20-80")
    r.add_argument("--move-mode", default="with", choices=["with", "against", "any"])
    r.add_argument("--btc", default="twap60", choices=["twap60", "price"], help="which stream measures the move")
    r.add_argument("--elapsed", help="seconds into the round, e.g. 180-285")
    r.add_argument("--stake", type=float, default=10.0, help="USD per trade")
    r.add_argument("--slippage", type=int, default=1, help="ticks added to each fill")
    r.add_argument("--csv", help="write every trade to this CSV file")

    d = sub.add_parser("download", help="download Chainlink files with your API key")
    d.add_argument("--from", dest="date_from", required=True)
    d.add_argument("--to", dest="date_to", required=True)
    d.add_argument("--key", help="API key (default: $POLYTICKTAPE_KEY)")

    a = ap.parse_args()
    if a.cmd == "run":
        if not a.sample and not (a.date_from and a.date_to):
            ap.error("run needs --from and --to, or --sample")
        return cli_run(a)
    if a.cmd == "download":
        return cli_download(a)
    serve(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
