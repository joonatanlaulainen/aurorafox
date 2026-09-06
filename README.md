# aurorafox

On-demand aurora watch for northern Europe. Answers one question:

> **Is a genuinely great aurora-viewing window opening in the next five days at
> Tromsø, Kiruna, Rovaniemi or Reykjavík — and where exactly should I drive?**

It combines live space-weather data (NOAA SWPC), live cloud forecasts (MET
Norway) and local astronomy into a conservative 1–10 score per night, and flags
anything at or above a threshold you set.

Runs on demand. No daemon, no scheduler, no stored state beyond an HTTP cache.

```bash
uv sync
uv run aurora-watch
```

```
** 2 NIGHT(S) AT OR ABOVE 7/10 **

  Reykjavik  Mon 07 Sep  8.29/10  23:00-03:00 (5h)
      -> Akranes, ~45 min from Reykjavik - 100% clear across 44 km with Reykjavik, Borgarnes, Hvalfjordur
```

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

MET Norway's terms require a User-Agent that identifies your application and
gives a contact address. Set your own before any real use:

```bash
export AURORAFOX_USER_AGENT="my-aurora-tool/1.0 me@example.com"
```

## Usage

```bash
uv run aurora-watch                              # all four cities, 5 days, threshold 7
uv run aurora-watch --city tromso --threshold 6  # one city, looser bar
uv run aurora-watch --json                       # machine-readable
uv run aurora-watch --city kiruna --explain      # hour-by-hour factor breakdown
```

Exit code is `0` when at least one night alerts and `1` otherwise, so it drops
straight into a shell alias or a notification hook.

```python
from aurorafox import run_aurora_watch

watch = run_aurora_watch(threshold=7.0, days=5)
for alert in watch.alerts:
    cluster = alert.best_cluster
    print(alert.city_key, alert.night, alert.score, cluster.anchor.name)
```

## How the score is built

```
raw = aurora_potential x sky_clarity x darkness x moon
score = 1 + 9 * raw ** 0.62
```

Clearing 7/10 needs `raw >= ~0.535`, which no single excellent factor can
deliver on its own. A pristine sky during a geomagnetically dead week does not
alert, and neither does a G2 storm under a solid overcast.

### What the scale is anchored to

The whole model is tuned to one fixed point: **at Tromsø, a fully clear region in
full darkness with no moon lands just on 7.0 at Kp 3, and clears it decisively at
Kp 4.** Everything else follows from that.

| Kp | Score, perfect clear dark night |
|---|---|
| 0 | 4.3 |
| 1 | 5.1 |
| 2 | 6.0 |
| **3** | **7.0** ← alert threshold |
| 4 | 8.0 |
| 5 | 9.0 |
| 6+ | 10.0 |

Roughly a point per Kp step, which is an emergent property of the calibration
rather than a design goal — but a useful one to preserve if you retune it.

That shape comes from a deliberately **non-linear** intensity curve
(`0.20 + 0.80·(Kp/6)^1.3`). An earlier linear form put a geomagnetically dead
Kp 0 night at 5.5/10 under a clear winter sky and let Kp 2 raise an alert. Both
were too generous: quiet-time aurora at these latitudes is a faint static arc,
while auroral power rises far faster than Kp itself does.

### Aurora potential — a band, not a ramp

The oval is a ring around the *geomagnetic* pole. Its equatorward edge marches
south as activity rises (`edge ≈ 66.5 − 2·Kp` in corrected geomagnetic latitude)
and it widens at the same time. A site scores best when the oval is overhead or
just to its north.

This is why the model is keyed on corrected geomagnetic latitude, not geographic:

| City | Geographic | Geomagnetic |
|---|---|---|
| Tromsø | 69.6 N | 66.6 |
| Kiruna | 67.9 N | 64.8 |
| Reykjavík | 64.1 N | 64.3 |
| Rovaniemi | 66.5 N | 63.3 |

Reykjavík is 2.4° *south* of Rovaniemi geographically but 1° *north* of it
geomagnetically, because the geomagnetic pole sits over Arctic Canada. A model
using geographic latitude ranks those two backwards.

The consequences are visible in the output. At Kp 0 only Tromsø is under the
oval. Between Kp 2 and 5 the oval covers all four and geometry stops
discriminating entirely. Past Kp 6 the oval slides south *past* Tromsø, which
ends up inside the polar cap with the aurora to its south.

So Tromsø's potential **peaks around Kp 6 and declines beyond it**, landing at
Kp 9 back around its Kp 3 level and some 40% below Rovaniemi's. The claim is
about where Tromsø peaks, not that a severe storm is bad there — at Kp 9 the sky
is still lit up, just increasingly to the south and increasingly less well placed
than sites further from the pole. A `score ∝ Kp` model has no way to express
this at all.

### Cloud — regions, not points

Forecast models place cloud bands roughly, not exactly. A single clear grid
point surrounded by cloud is more likely a positioning error than a hole you can
drive to. So **no location scores on its own**:

- Each point is tried as an anchor for a cluster of points within **40 km**.
- An anchor with fewer than **3** points in range is **ineligible entirely**,
  however clear it looks.
- The cluster scores at the **30th percentile** of its members — "at least ~70%
  of the sampled area within 40 km is at least this clear".

Cloud layers are weighted separately, because for aurora it matters far more
*which* cloud is in the way than how much: low cloud 0.55, medium 0.30, high
0.15, with fog and precipitation close to disqualifying.

Each city has 15–16 curated, road-accessible viewing sites — 61 in total —
chosen so that outlying areas can still form eligible clusters rather than being
silently unreachable by the scoring.

### Darkness and moon

Darkness comes from solar altitude on a continuous ramp: zero above −6°, 0.55 at
the nautical boundary, 1.0 at −18°. At these latitudes this is not a refinement
but the dominant seasonal gate — from mid-May to late July the sun never reaches
−6° at Tromsø or Kiruna and the tool correctly reports no viable window at any
score.

Moonlight applies a moderate penalty scaled by illuminated fraction *and* moon
altitude (a set moon costs nothing), softened when aurora potential is high,
since a strong display punches through moonlight that would erase a faint arc.

### Horizon — the part that makes it conservative

Forecast skill collapses with lead time, and the two inputs collapse at very
different rates. MET's cloud forecast degrades gracefully across five days.
NOAA's Kp forecast simply **stops at about 72 hours**, after which the only
signal is a daily maximum from a 27-day recurrence table that may be a week old.

| Horizon | Aurora source | conf | Sky conf |
|---|---|---|---|
| 0–12 h | Kp + OVATION nowcast + live Bz | 1.00 | 1.00 |
| 12–24 h | 3-hourly Kp forecast | 0.90 | 0.95 |
| 24–48 h | 3-hourly Kp forecast | 0.80 | 0.85 |
| 48–72 h | Kp forecast (edge of range) | 0.65 | 0.75 |
| 72–120 h | 27-day outlook daily max only | 0.40 | 0.60 |

Confidence is applied as a **shrink toward a pessimistic prior**, not a multiply:

```
adjusted = prior + confidence * (value - prior)
```

A multiply would only make an uncertain day-5 signal *smaller*, which still lets
a spuriously exciting one clear the threshold when other factors are high.
Shrinking pulls it toward "ordinary" instead — the honest statement being that
at five days out we do not know.

**Days 4–5 are hard-capped at 6.0 and can never alert.** They surface instead on
a separate clear-sky watchlist, which tells you where to look again in two days
without pretending to aurora skill that does not exist.

Two further guards: a night qualifies only with **≥2 consecutive hours** above
threshold, so a single flukey hour is not reported as a window; and the final
night, clipped by the forecast horizon, is reported but never alerts.

## Data sources

| Source | Product | What it gives |
|---|---|---|
| MET Norway | `locationforecast/2.0/complete` | Cloud by layer, fog, humidity, precipitation. Hourly to ~t+65h, then 6-hourly to 9 days. |
| NOAA SWPC | `noaa-planetary-k-index-forecast.json` | 3-hourly Kp, observed and predicted, ~72 h ahead. |
| NOAA SWPC | `ovation_aurora_latest.json` | 1°×1° aurora probability grid — a nowcast, ~30–90 min. |
| NOAA SWPC | `geospace/propagated-solar-wind-1-hour.json` | Live Bz/Bt/speed/density at the magnetopause. |
| NOAA SWPC | `27-day-outlook.txt` | Daily largest Kp — the only signal past 72 h. |
| NOAA SWPC | `alerts.json` | Storm watches, warnings and CME alerts. |

Two notes for anyone extending this. `fog_area_fraction` **disappears** from
MET's payload beyond the hourly section, so it is parsed as `None` and proxied
from humidity rather than read as zero — treating its absence as "no fog" would
systematically flatter days 4–5. And the widely-cited SWPC paths
`solar-wind/mag-1-day.json` and `plasma-1-day.json` return 404; the
`geospace/propagated-*` product is the working replacement.

Responses are cached on disk (`~/.cache/aurorafox`, or `AURORAFOX_CACHE_DIR`),
honouring MET's `Expires` header. A cold run takes ~1.5 s; a warm one ~0.2 s.

Every source degrades independently. If MET fails for one point, that point
drops out of its clusters — which may make an anchor ineligible, the correct
conservative response. If the Kp forecast fails entirely, the run says so in
`warnings` rather than substituting a default.

## Development

```bash
uv run pytest              # 113 offline tests, no network
uv run pytest -m live      # smoke tests against the real APIs
```

The scale is anchored by a **calibration table** of named reference scenarios in
`tests/test_scoring.py`, from "polar night, Kp 5, region clear, no moon" → 8.77
down to "overcast, raining, twilight" → 1.19, with "polar night, Kp 3, fully
clear, no moon" → 7.04 as the threshold anchor. To make the estimator harsher or
more generous, change the intensity curve, `SCORE_GAMMA`, the priors, or the tier
confidences, then read off which scenarios moved. That is a far more legible way
to tune it than adjusting magic numbers and hoping.

The intensity curve is the right lever for "it over-scores"; `SCORE_GAMMA` is a
blunter one that compresses the whole range uniformly, barely moving the top end
while flattening the middle.

The live tests exist to catch the failure mode that actually bites: an upstream
product quietly changing shape or horizon. `test_kp_forecast_still_stops_around_three_days`
will fail if SWPC ever extends that product, which would be a reason to revisit
the horizon tiers.

## Limitations

- Weights are a documented heuristic, not calibrated against observed sightings.
  There is no historical verification loop.
- Cloud is sampled at 15–16 points per city, not a gridded field. Terrain-driven
  cloud between sampled points is invisible.
- No ensemble spread, so the score is a point estimate with no error bar; the
  horizon tiers are a proxy for uncertainty, not a measurement of it.
- Corrected geomagnetic latitudes are fixed constants for epoch ~2025 and drift
  slowly; they will need revisiting in a decade.
- Light pollution is not modelled. Drive-time estimates are rough.

## Licence

MIT — see [LICENSE](LICENSE).
