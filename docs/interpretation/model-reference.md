# Model reference

How each factor is produced, and from what. Read this when you need to explain
*why* a score is what it is.

## The four factors

```
raw = aurora × sky × darkness × moon
```

### Aurora (0–1) — a band, not a ramp in Kp

The auroral oval is a ring around the **geomagnetic** pole. Its equatorward edge
marches south as activity rises (`edge ≈ 66.5 − 2·Kp`, in corrected geomagnetic
latitude) and it widens at the same time. A site scores best when the oval is
overhead or just to its north.

Because of this the model is keyed on **corrected geomagnetic latitude**, not
geographic latitude:

| City | Geographic | Geomagnetic |
|---|---|---|
| Tromsø | 69.6 N | 66.6 |
| Kiruna | 67.9 N | 64.8 |
| Reykjavík | 64.1 N | 64.3 |
| Rovaniemi | 66.5 N | 63.3 |

Reykjavík is 2.4° *south* of Rovaniemi geographically but 1° *north*
geomagnetically, because the geomagnetic pole sits over Arctic Canada. A model
using geographic latitude ranks those two backwards.

Consequences visible in output:

- **Kp 0** — only Tromsø is under the oval.
- **Kp 2–5** — the oval covers all four; geometry stops discriminating entirely
  and the `site_position` field reads `"inside"` everywhere.
- **Kp 6+** — the oval slides south past Tromsø. Tromsø's potential **peaks
  around Kp 6 and declines beyond**, reaching Kp 9 at roughly its Kp 3 level and
  about 40% below Rovaniemi's. `site_position` becomes `"poleward"`.

Intensity rises non-linearly with Kp: `0.20 + 0.80·(Kp/6)^1.3`, saturating at
Kp 6. Near magnetic midnight the potential is weighted up; a site 6+ hours from
magnetic midnight is weighted down to as low as 0.45.

Within the next ~3 hours only, two extra inputs sharpen this: the OVATION
nowcast (blended in with 25–50% weight) and live solar-wind Bz/speed. Beyond 3
hours neither carries information and both are ignored.

### Sky (0–1) — regions, not points

Cloud layers are weighted separately, because *which* cloud is in the way matters
far more than how much:

```
sky = 1 − 0.55·low − 0.30·medium − 0.15·high      (fractions)
sky × = (1 − fog)
sky × = precipitation penalty                     (0.5 mm/h ⇒ zero)
```

**Then the coherence rule**, which is the part that makes the number trustworthy:

- Every site is tried as a cluster **anchor**.
- An anchor needs **≥3 sampled sites within 40 km** or it is *ineligible
  entirely*, however clear it looks alone.
- The cluster scores at the **30th percentile** of its members — read as "at
  least ~70% of the sampled area within 40 km is at least this clear".
- The city's sky score is the best eligible cluster.

The 30th percentile rather than the minimum is deliberate: one cloudy fjord
should not veto a genuinely clear region, but one clear valley should not carry a
cloudy one either.

Beyond ~65 h MET stops sending `fog_area_fraction` entirely. It is parsed as
`None` and proxied from humidity at a capped penalty — never read as "no fog",
which would systematically flatter exactly the days with least skill.

### Darkness (0–1) — the dominant seasonal gate

From solar altitude, on a continuous ramp:

| Sun altitude | darkness |
|---|---|
| above −6° | **0.0 — hard gate, score forced to 1.0** |
| −6° to −12° | 0.0 → 0.55 |
| −12° to −18° | 0.55 → 1.0 |
| below −18° | 1.0 |

At these latitudes this is not a refinement. From mid-May to late July the sun
never reaches −6° at Tromsø or Kiruna, and the tool correctly reports no viable
window at any score. In early September Tromsø bottoms out near −14° (nautical
twilight, darkness ≈ 0.63) while Reykjavík reaches −18° — which is why Reykjavík
outscores it in autumn.

### Moon (0–1)

`1 − k · illuminated_fraction · f(altitude)`. A moon **below the horizon costs
nothing** whatever its phase — this is why phase alone is a poor predictor. The
penalty is softened when aurora potential is high, since a strong display punches
through moonlight that would erase a faint arc. Worst case is about −30%.

## Horizon tiers and the confidence shrink

Forecast skill collapses with lead time, and the two inputs collapse at very
different rates. MET degrades gracefully across five days; NOAA's Kp forecast
**stops dead at ~72 h**.

| Horizon | Aurora source | Aurora conf | Sky conf |
|---|---|---|---|
| 0–12 h | Kp + OVATION nowcast + live Bz | 1.00 | 1.00 |
| 12–24 h | 3-hourly Kp forecast | 0.90 | 0.95 |
| 24–48 h | 3-hourly Kp forecast | 0.80 | 0.85 |
| 48–72 h | Kp forecast (edge of range) | 0.65 | 0.75 |
| 72–120 h | 27-day outlook daily max only | 0.40 | 0.60 |

Confidence is applied as a **shrink toward a pessimistic prior**, not a multiply:

```
adjusted = prior + confidence × (value − prior)      # prior: aurora 0.40, sky 0.45
```

A multiply would only make an uncertain day-5 signal *smaller*, which still lets
a spuriously exciting one clear the threshold when the other factors are high.
Shrinking pulls it toward "ordinary" instead — the honest statement being that at
five days out we do not know.

Past 72 h the score is additionally **hard-capped at 6.0** and cannot alert.

## Data sources

| Source | Product | Horizon / nature |
|---|---|---|
| MET Norway | `locationforecast/2.0/complete` | Cloud by layer, fog, humidity, precipitation. Hourly to ~65 h, then 6-hourly to 9 days. |
| NOAA SWPC | `noaa-planetary-k-index-forecast.json` | 3-hourly Kp, observed + predicted. **Stops at ~72 h.** |
| NOAA SWPC | `ovation_aurora_latest.json` | 1°×1° aurora probability grid. **Nowcast, ~30–90 min.** |
| NOAA SWPC | `geospace/propagated-solar-wind-1-hour.json` | Live Bz/Bt/speed/density at the magnetopause. |
| NOAA SWPC | `27-day-outlook.txt` | Daily *largest* Kp from coronal-hole recurrence. Only signal past 72 h; can be a week stale. |
| NOAA SWPC | `alerts.json` | Storm watches/warnings; raises the potential *floor*, does not scale it. |

Sun and moon geometry are computed locally with `ephem`; no network involved.

## Guards against false positives

1. **Cluster eligibility** — an isolated clear point cannot score at all.
2. **≥2 consecutive hours** above threshold for a night to qualify.
3. **Darkness hard gate** at −6° solar altitude.
4. **Day 4–5 cap** at 6.0.
5. **Truncated final night** reported but never allowed to alert.
6. **Confidence shrink toward a pessimistic prior**, not a multiply.
7. **Missing data never reads as favourable** — no cluster means no eligible
   place to stand, and the sky factor is floored at 0.25 rather than shrunk
   toward the prior.

## Known limitations

- Weights are documented heuristics, **not calibrated against observed
  sightings**. There is no historical verification loop.
- Cloud is sampled at 15–16 points per city, not a gridded field. Terrain-driven
  cloud between sampled sites is invisible.
- No ensemble spread, so no error bar. The horizon tiers are a *proxy* for
  uncertainty, not a measurement of it.
- Geomagnetic latitudes are fixed constants for epoch ~2025 and drift slowly.
  Published AACGM values run 0.1–0.4° above those used here — near-zero effect in
  the Kp 2–5 range where the band response is flat.
- Light pollution is not modelled. Drive times are rough.
