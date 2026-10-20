# Sample: 2026-09-20 04:00–05:00 UTC

| File | What | SHA-256 |
|---|---|---|
| `btc-twap60-2026-09-20T04.jsonl.gz` | Chainlink BTC/USD TWAP60, 3,572 rows | `07a3479f863e6bdb89a359f5081632be505f0d6c012db8238000eb01c215dcf9` |
| `btc-price-2026-09-20T04.jsonl.gz` | Chainlink BTC/USD price, 3,571 rows | `00f54486842f8add73013d37bdd8baaf1d5039fe81cdf63f0cc07eb4085b62a4` |
| `odds-2026-09-20.json.gz` | The hour's 12 rounds: Polymarket's resolution and 3,389 taker-BUY prices (highest per second and side) | `4188b4a9ca68e8eff5d722d3bcca44bae5a04e2ca3021bb6f49261809111d86f` |

The Chainlink files cover 04:00:00 to 04:59:59 plus the 05:00:00 row, so the hour's last round can be settled. Lines are byte for byte as in the published day files, and missing seconds are left missing. All 12 rounds settle on TWAP60 the way Polymarket resolved them.

The odds file was built by `odds.py` from Polymarket's public Gamma and Data APIs, so `python backtest.py run --sample` works offline.

License for the two Chainlink files: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Use them for research with attribution to "Poly Tick Tape (polyticktape.com)". Resale isn't allowed.

Every UTC day since 2026-08-14: https://polyticktape.com/?ref=bt
