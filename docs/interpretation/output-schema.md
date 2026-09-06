# Output schema (`aurora-watch --json`)

Produced by `aurorafox.cli._to_json()`. All times are **ISO 8601 with UTC
offset**. All 0–1 factors are floats.

> **Naming trap.** The city identifier has three different key names depending on
> where you are in the document: `alerts[].city`, `clear_sky_watchlist[].city_key`,
> and `cities[].key`. All three hold the same value (`"tromso"`, `"kiruna"`,
> `"rovaniemi"`, `"reykjavik"`). Handle all three when joining across sections.

## Top level

| Field | Type | Meaning |
|---|---|---|
| `version` | str | Package version that produced this. |
| `generated_at` | str | Reference time the run was scored against. |
| `threshold` | float | Alert threshold in force (default 7.0). |
| `days` | int | Horizon requested. |
| `alerts` | array | **Qualifying** nights ≥ threshold, best first. Often empty. |
| `clear_sky_watchlist` | array | Days 4–5 cloud-only signal. **Not aurora.** |
| `cities` | array | Full per-night breakdown for every city scored. |
| `sources` | array | Provenance and status of each upstream product. |
| `warnings` | array[str] | Degradation notices. Non-empty ⇒ treat scores as floors. |

## `alerts[]`

The actionable output. **Read this rather than filtering `cities[].nights[]`
yourself** — membership already accounts for the ≥2-consecutive-hour rule, the
day 4–5 cap, and truncated nights.

| Field | Type | Meaning |
|---|---|---|
| `city` | str | City key. |
| `night` | str | `YYYY-MM-DD`, dated by the **evening you set out**, so a 02:00 peak belongs to the previous date. |
| `score` | float | Peak hourly score that night. |
| `window_start` / `window_end` | str | First and last hour at or above threshold. |
| `window_hours` | int | Length of that window, always ≥ 2. |
| `anchor` | str | **The site to drive to.** The most useful single field. |
| `sites` | array[str] | Cluster members backing the anchor, clearest first. |
| `cluster_sky` | float | 30th-percentile clarity across the cluster, 0–1. |
| `cluster_span_km` | float | Maximum separation within the cluster. |
| `kp` | float | Kp at the peak hour. |
| `kp_source` | str | Which product supplied it — see `sources` note below. |
| `limiting_factor` | str | Weakest factor even in an alerting night. |

## `clear_sky_watchlist[]`

**Cloud only. Contains no aurora information.** Days 4–5 cannot alert because no
aurora forecast reaches that far, so this exists to say "conditions may be clear
here — re-run in two days".

| Field | Type | Meaning |
|---|---|---|
| `city_key` | str | City key. |
| `night` | str | Night date. |
| `sky` | float | Best cluster clarity that night, 0–1. |
| `dark_hours` | int | Hours dark enough to be worth scoring. |
| `anchor` | str | Best cluster anchor. |
| `lead_days` | float | Days ahead. Always > 3. |

## `cities[]`

| Field | Type | Meaning |
|---|---|---|
| `key`, `name` | str | Identifier and display name. |
| `cgm_latitude` | float | Corrected geomagnetic latitude — drives oval geometry. |
| `points_used` | int | Viewing sites with usable forecasts. |
| `points_failed` | array[str] | Sites whose forecast could not be fetched. |
| `nights` | array | Per-night detail, chronological. |

### `cities[].nights[]`

| Field | Type | Meaning |
|---|---|---|
| `night` | str | Night date (evening you set out). |
| `score` | float | **Peak** hourly score for the night. |
| `qualifies` | bool | **Whether this is an alert.** May be `false` with `score ≥ threshold`. |
| `truncated` | bool | Night clipped by the horizon; reported but never alerts. |
| `dark_hours` | int | `0` ⇒ never dark enough; the score will be 1.0. |
| `peak_time` | str | Hour of the peak score. |
| `window_start` / `window_end` | str \| null | `null` when no sustained window formed. |
| `tier` | str | Horizon band, e.g. `"0-12 h"`, `"72-120 h"`. |
| `aurora_potential` | float | Raw aurora factor before confidence shrink. |
| `aurora_adjusted` | float | **After** shrink. This is what fed the score. |
| `sky` | float | Raw cluster clarity. |
| `sky_adjusted` | float | After shrink. This is what fed the score. |
| `darkness` | float | 0 above −6° sun, 0.55 at −12°, 1.0 below −18°. |
| `moon_factor` | float | 1.0 = moonlight costs nothing. |
| `moon_illumination` | float | Illuminated fraction, 0–1. |
| `kp`, `kp_source` | float, str | Kp and where it came from. |
| `site_position` | str | `"inside"`, `"equatorward"`, `"poleward"` — site vs the oval band. |
| `anchor` | str \| null | `null` ⇒ **no coherent clear region existed**. |
| `cluster_sites` | array[str] | Members of the best cluster. |
| `cluster_span_km` | float \| null | Extent of that cluster. |
| `clear_point_count` | int | Diagnostic: sites with clarity ≥ 0.70. |
| `clear_span_km` | float | Diagnostic: extent of those clear sites. |
| `capped` | bool | **`true` ⇒ score was clamped to 6.0** for being past 72 h. |
| `limiting_factor` | str | See below. |

### `limiting_factor` values

One of: `"cloud"`, `"aurora activity"`, `"darkness"`, `"moonlight"`,
`"not dark (sun above -6 deg)"`, `"cloud (no coherent clear region found)"`, or
`"nothing in particular - all factors favourable"`.

This is usually the most useful field for explaining a low score, because it says
whether re-running later could change the answer. `cloud` might improve;
`darkness` in June will not.

## `sources[]`

| Field | Type | Meaning |
|---|---|---|
| `name` | str | Product name. |
| `status` | str | `"ok"` or `"unavailable"`. |
| `fetched_at` | str \| null | When it was retrieved. |
| `issued_at` | str \| null | When the *provider* issued it — the staleness signal. |
| `detail` | str | Free text, e.g. failure reason. |

Check `issued_at` on the 27-day outlook in particular: it can legitimately be a
week old, which is exactly why days 4–5 are capped.

## Interpreting `kp_source`

| Value | Trust |
|---|---|
| `"observed Kp"` | Measured. Highest confidence. |
| `"SWPC 3-hourly Kp forecast"` | Real forecast. Good to ~72 h. |
| `"27-day outlook (daily max Kp)"` | **Weak.** A daily *maximum* from coronal-hole recurrence, possibly a week stale, discounted by 0.7 before use. Days 4–5 only. |
| `"unavailable"` | No geomagnetic data. The score is a floor. |
