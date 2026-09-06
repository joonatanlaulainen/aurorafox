# Reading results: worked examples

Output shapes, with the reasoning you should apply to them.

Examples 1 and 2 are taken verbatim from real runs. Examples 3–5 are
*illustrative* — they show shapes that occur but that happened not to be present
in the run used here, and are labelled as such.

---

## Example 1 — an alert *(real output)*

```json
{
  "city": "reykjavik", "night": "2026-09-07", "score": 7.33,
  "window_start": "2026-09-08T00:00:00+00:00",
  "window_end":   "2026-09-08T02:00:00+00:00", "window_hours": 3,
  "anchor": "Akranes",
  "sites": ["Reykjavik", "Borgarnes", "Hvalfjordur", "Akranes"],
  "cluster_sky": 0.9988, "cluster_span_km": 43.6,
  "kp": 4.0, "kp_source": "SWPC 3-hourly Kp forecast",
  "limiting_factor": "aurora activity"
}
```

**A good summary:** *"Reykjavík, the night of Sunday 7 September — about 7/10,
the best window this week. Head to Akranes, roughly 45 minutes out; the sky is
forecast essentially clear across a 44 km region including Borgarnes and
Hvalfjörður. Best between 00:00 and 02:00 local. Kp 4 from the real 3-hourly
forecast, so this is a solid signal rather than a long-range guess."*

Points to note:

- The `night` is `2026-09-07` but the window is on the **8th** in UTC. Nights are
  dated by the evening you set out. Both are correct; say "the night of the 7th".
- `limiting_factor: "aurora activity"` in an *alerting* night means everything
  else was near-perfect and Kp 4 was the binding constraint. It is not a warning.
- `cluster_span_km: 43.6` is the point of the whole cloud model — a 44 km clear
  region, not one lucky grid point.

---

## Example 2 — a peak that is **not** an alert *(real output, `--threshold 6`)*

```json
{
  "night": "2026-09-06", "score": 6.13, "qualifies": false,
  "window_start": null, "window_end": null,
  "dark_hours": 7, "truncated": false
}
```

Hourly detail behind it (UTC, threshold 6.0):

```
20:00  4.57   21:00  5.45   22:00  5.86   23:00  5.76
00:00  6.13 ←peak        01:00  4.67   02:00  2.19
```

**Do not report this as an alert.** One hour touches 6.13, bracketed by 5.76 and
4.67. The ≥2-consecutive-hour rule correctly rejects it: darkness is collapsing
fast (0.95 → 0.92 → 0.77 → 0.51 across those hours), so there is no sustained
window. The same logic applies at the default threshold of 7.0.

**A good summary:** *"Rovaniemi briefly touches the bar around midnight but only
for a single hour — darkness is fading too quickly either side of it for a real
window. Not worth the drive."*

**The rule:** if `qualifies` is `false`, it is not an alert, whatever `score`
says. Trust `qualifies`, or just read the `alerts` array.

---

## Example 3 — a capped long-range night *(illustrative)*

```json
{
  "night": "2026-09-10", "score": 6.00, "capped": true,
  "tier": "72-120 h", "kp": 1.30,
  "kp_source": "27-day outlook (daily max Kp)"
}
```

`capped: true` means the raw score was clamped to the 6.0 ceiling. The true
computed value may have been higher — **it is not reported and should not be
inferred**. Treat `6.00 + capped` as "we cannot say", not as "just below alert".

The flag is uncommon: it only fires when a day 4–5 night would *otherwise* have
scored above 6.0. Most long-range nights score well below the cap on their own,
in which case `capped` is `false` and the score is the real computed value.

**A good summary:** *"Four to five days out there is no real aurora forecast —
only a daily maximum from a 27-day recurrence table. This night is capped and
cannot alert. Re-run in two days for an actual answer."*

---

## Example 4 — no clear region at all *(illustrative)*

```json
{ "score": 3.06, "anchor": null, "cluster_sites": [],
  "clear_point_count": 0, "limiting_factor": "cloud (no coherent clear region found)" }
```

`anchor: null` does **not** mean missing data. It means every candidate site
failed the coherence rule: no site had ≥3 sampled points within 40 km that were
collectively clear enough. Either it is broadly cloudy, or the only clear spots
are isolated — which the model deliberately refuses to recommend, because an
isolated clear point is more likely a forecast positioning error than a real hole.

Distinguish this from **missing data**, which shows as `points_failed` being
non-empty on the city, plus entries in `warnings`.

---

## Example 5 — a degraded run *(illustrative; reproducible by blocking SWPC)*

```json
{ "warnings": [
    "SWPC 3-hourly Kp forecast unavailable: HTTP 503",
    "No geomagnetic forecast available at all - aurora potential cannot be
     estimated and every score below is a floor, not an estimate."
  ],
  "sources": [{"name": "SWPC 3-hourly Kp forecast", "status": "unavailable"}] }
```

**Always surface this.** The run completed and every field is populated, but the
scores are floors, not estimates. Saying "nothing above 3/10 this week" without
mentioning the outage would be actively misleading — the sky data is fine and the
aurora data is simply absent.

---

## Misreadings to avoid

| Misreading | Why it is wrong |
|---|---|
| "7.33 means a 73% chance" | The score is **not a probability**. Never convert it to a percentage. |
| Filtering `nights[]` by `score ≥ 7` to find alerts | Misses the ≥2-hour rule, the day 4–5 cap and truncation. Use `alerts`. |
| Ranking a day-5 score against a day-1 score | Different tiers, different caps. Not the same measurement. |
| "Reykjavík beats Tromsø, so the geomagnetic model is wrong" | In autumn Reykjavík gets genuinely darker. Correct physics. |
| "Kp 7 is coming, so Tromsø will be best" | Tromsø peaks near Kp 6 and declines beyond — the oval slides south past it. |
| Quoting `clear_sky_watchlist` as an aurora forecast | It is cloud only, and contains no aurora information whatever. |
| "Score 1.0, so a terrible aurora night" | 1.0 usually means **not dark** — the question does not apply. Check `dark_hours`. |
| Averaging scores across a week | Scores are peaks of independent nights on a non-linear scale. Meaningless. |
| Reporting `aurora_potential` as the driver | `aurora_adjusted` is what actually fed the score. |

## A note on seasons

| Period | What to expect |
|---|---|
| **May–July** | Nothing scores above 1.0 anywhere. Midnight sun. This is correct, not a failure. |
| **Aug–Sep** | Reykjavík and Rovaniemi favoured — far enough south for real astronomical night. |
| **Oct–Mar** | All four fully dark; cloud and Kp decide. Tromsø and Kiruna favoured on geomagnetic latitude. |
| **Apr** | Darkness shrinking again, northern sites first to lose it. |

If someone asks "why is nothing showing up in June", the answer is the sun, not
the tool.
