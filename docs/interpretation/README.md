# Interpreting an aurorafox result

**Audience: an LLM (or person) handed the output of `run_aurora_watch()` who did
not run it and cannot see the code.**

This page is self-contained. Read only this if you are short on context; the
other files in this folder are depth on specific points.

- [`score-scale.md`](score-scale.md) — what a number from 1 to 10 actually means
- [`output-schema.md`](output-schema.md) — every JSON field, with types and traps
- [`reading-results.md`](reading-results.md) — worked examples, and the misreadings to avoid
- [`model-reference.md`](model-reference.md) — how the score is built, and from what data

---

## What the tool does

It estimates whether an aurora will be **visible from a specific place at a
specific hour** over the next five days, at four destinations: **Tromsø**
(Norway), **Kiruna** (Sweden), **Rovaniemi** (Finland) and **Reykjavík**
(Iceland). Each city carries 15–16 curated, road-accessible viewing sites.

It is not a Kp forecast and not a cloud forecast. It is an estimate of *visible
aurora*, which requires geomagnetic activity **and** clear sky **and** darkness
simultaneously.

## The one-paragraph version

Every dark hour gets `score = 1 + 9 · (aurora × sky × darkness × moon)^0.62`,
where each factor is 0–1. **7.0 is the default alert threshold**, calibrated so
that at Tromsø a fully clear region in full darkness with no moon lands exactly
on 7.0 at **Kp 3**, and on 8.0 at Kp 4. Roughly one point per Kp step. Scores are
deliberately conservative: forecast confidence shrinks each factor toward a
pessimistic prior as the horizon lengthens, and **days 4–5 are hard-capped at 6.0
and can never alert**, because no aurora forecast exists that far out.

## The five things most likely to be misread

**1. A score of 7+ is not automatically an alert.** A night qualifies only with
**≥2 consecutive hours** above threshold. A single hour at 7.3 bracketed by 6.7
and 5.5 is a fluke, not a window worth driving for. Always check `qualifies`, or
just read the `alerts` array — do not filter `cities[].nights[]` by score
yourself.

**2. Day-5 scores are not comparable to day-1 scores.** Beyond 72 h the score is
capped at 6.0 (`capped: true`). A day-5 "5.8" and a day-1 "5.8" are not the same
statement. Never rank nights across horizons by raw score.

**3. Reykjavík outscoring Tromsø in autumn is correct, not a bug.** At 64°N
Reykjavík reaches true astronomical night in early September; Tromsø at 69.6°N
only reaches −14° and sits in nautical twilight. Further south is an *advantage*
in Aug–Sep and a liability in midwinter. In May–July **no** location can score
above 1.0 — the sun never sets far enough.

**4. Higher Kp is not monotonically better everywhere.** The auroral oval moves
*south* as activity rises. Tromsø's potential peaks around **Kp 6** and declines
beyond it, because the oval slides past and leaves it in the polar cap. At Kp 9
Tromsø is ~40% worse placed than Rovaniemi.

**5. `clear_sky_watchlist` says nothing about aurora.** It is a *cloud-only*
signal for days 4–5, meaning "the sky may be clear here, re-run in two days when
a real aurora forecast exists". Never present it as an aurora prediction.

## How to summarise a result well

1. Lead with the verdict: the `alerts` array, or plainly that nothing qualifies.
2. For each alert, give **city, night, score, the time window, and the named
   anchor site** — the anchor is the actionable part, not the city.
3. For non-alerting nights, `limiting_factor` says *why*. That is usually the
   most useful thing you can tell someone, because it says whether re-running
   tomorrow could change the answer (`cloud` might; `darkness` in June will not).
4. If `warnings` is non-empty, say so. Scores in a degraded run are floors, not
   estimates.
5. Do not present scores as precise. They are a documented heuristic, not
   calibrated against observed sightings. "About 7" is honest; "7.33, so a 73%
   chance" is not — **the score is not a probability**.

## What the tool cannot tell you

No historical verification against actual sightings. Cloud is sampled at 15–16
points per city, not a gridded field, so terrain-driven cloud between sites is
invisible. No ensemble spread, so there is no error bar — the horizon tiers are a
proxy for uncertainty, not a measurement of it. Light pollution is not modelled.
Drive times are rough estimates.
