# CLAUDE.md

Guidance for Claude Code working in this repository.

> Interpreting a *result* rather than editing the code? Read
> [`docs/interpretation/README.md`](docs/interpretation/README.md) instead.

## What this is

`run_aurora_watch()` scores the next five days for visible aurora at Tromsø,
Kiruna, Rovaniemi and Reykjavík, combining NOAA SWPC space weather, MET Norway
cloud forecasts and local astronomy into a conservative 1–10 score per night.
Runs on demand; no daemon, no state beyond an HTTP cache.

## Commands

```bash
uv sync                    # create env from the lock
uv run pytest              # full offline suite (~130 tests), ~0.7 s, no network
uv run pytest -m live      # 6 smoke tests against the real APIs
uv run aurora-watch        # the CLI
uv run aurora-watch --json --explain
uvx ruff check src tests --select F,E9,W,ARG,B,SIM --line-length 100
```

Python 3.11+, managed with `uv`. Dependencies are `requests` and `ephem` only —
keep it that way unless there is a strong reason.

## Layout

```
src/aurorafox/
  watch.py            run_aurora_watch() — orchestration, failure policy
  locations.py        City/ViewingPoint registry (61 curated sites)
  astronomy.py        ephem wrappers: darkness, moon
  geo.py              haversine, percentile, clamp
  sources/http.py     cached session, User-Agent policy, Expires handling
  sources/metno.py    cloud forecast -> hourly PointForecast
  sources/swpc.py     Kp forecast, OVATION, solar wind, 27-day, alerts
  scoring/aurora.py   A(t) — oval band model
  scoring/sky.py      per-point clarity + spatial clustering
  scoring/combine.py  horizon tiers, confidence shrink, 1-10 scale
  report.py, cli.py   text/JSON rendering
```

## Invariants — do not break these silently

**The calibration anchor.** At Tromsø, a fully clear region in full darkness with
no moon must score **exactly 7.0 at Kp 3** and ≥8.0 at Kp 4. Pinned by
`test_tromso_threshold_anchor_is_kp_three_under_a_perfect_sky`. The ~1 point per
Kp step that falls out of this is also pinned. If you retune scoring, change the
**calibration table** in `tests/test_scoring.py` and read off which named
scenarios moved — do not adjust constants until tests go green.

**Aurora potential is a band response, not a ramp in Kp.** Keyed on
`cgm_latitude`. Tromsø's potential *peaks near Kp 6 and declines beyond*. Any
change making potential monotonic in Kp is a regression.

**No location scores on its own.** A cluster anchor needs ≥3 sites within 40 km
or it is ineligible entirely; clusters score at the 30th percentile. This exists
to reject isolated clear points, which are usually forecast positioning error.
If you add viewing points, run `test_enough_anchors_can_form_clusters` — it
catches sites too isolated to ever be recommended.

**Missing data must never read as favourable.** MET drops `fog_area_fraction`
past ~65 h; it is parsed as `None` and proxied from humidity, never as zero. No
cluster floors the sky factor at 0.25 rather than shrinking it toward the prior.

**Confidence shrinks toward a pessimistic prior, it does not multiply.** Aurora
and sky confidence decay separately because the products do — MET degrades
gracefully, NOAA's Kp forecast stops dead at ~72 h. Days 4–5 are capped at 6.0
and must never alert.

**Sources degrade, never crash.** A failed product appends to `warnings` and sets
`status: "unavailable"`. A failed point drops out of its clusters.

## Upstream facts worth not rediscovering

- SWPC's 3-hourly Kp forecast reaches only **~72 h**. Past that the sole signal
  is `27-day-outlook.txt`, a daily *maximum* that can be a week stale.
- `ovation_aurora_latest.json` is a **nowcast** (~30–90 min), not a forecast.
- `solar-wind/mag-1-day.json` and `plasma-1-day.json` **return 404**. Use
  `geospace/propagated-solar-wind-1-hour.json`.
- MET switches from hourly to 6-hourly at ~65 h and drops fields there.
- MET's terms require an identifying `User-Agent` with contact info
  (`AURORAFOX_USER_AGENT`) and respecting the `Expires` header.

## Testing conventions

Offline tests use recorded fixtures in `tests/fixtures/` and must stay
deterministic and network-free — `addopts = "-m 'not live'"` enforces this.
Live tests exist to catch upstream products changing shape or horizon; when one
fails, that is usually real news about the API, not a broken test.

`run_aurora_watch(now=...)` takes an injectable reference time — use it rather
than mocking clocks.

`tests/test_docs.py` asserts that every constant and calibration figure quoted in
`docs/interpretation/` matches the code. Those docs are consumed by an LLM that
cannot see this repository, so silently drifted documentation is worse than none.
If you retune the model, that test tells you which sentences need rewriting.

## Style

Comments explain *why*, especially where a choice is non-obvious or a naive
alternative would be wrong. Several constants encode real physics; keep their
rationale next to them. Prefer editing the calibration table over adding new
magic numbers.
