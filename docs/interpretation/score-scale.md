# The 1–10 scale

## Formula

```
raw   = aurora_adjusted × sky_adjusted × darkness × moon_factor    # each 0–1
score = 1 + 9 × raw ^ 0.62                                          # 1.0 – 10.0
```

Clearing 7.0 requires `raw ≥ ~0.52`. Because the factors multiply, **no single
excellent factor can carry the score**. A pristine sky in a geomagnetically dead
week does not alert; neither does a severe storm under overcast.

## The anchor

The model is tuned to one fixed point:

> At Tromsø, a **fully clear region in full darkness with no moon** lands exactly
> on **7.0 at Kp 3**, and clears it decisively at Kp 4.

| Kp | 0 | 1 | 2 | **3** | 4 | 5 | 6+ |
|---|---|---|---|---|---|---|---|
| Score | 4.3 | 5.1 | 6.0 | **7.0** | 8.0 | 9.0 | 10.0 |

Roughly **one point per Kp step** under otherwise perfect conditions. This is an
emergent property of the calibration rather than a design goal, but it is pinned
by a test, so you can rely on it.

Those numbers assume everything else is perfect. Real nights are lower: any cloud,
any twilight, any moon multiplies the score down.

## Rough reading of a score

| Score | Meaning |
|---|---|
| 9–10 | Exceptional. Strong activity, clear region, full darkness. Rare. |
| 7–9 | **Alerts.** Genuine activity and a genuinely clear region. Worth driving for. |
| 6–7 | Good but something is short — usually cloud, twilight, or only moderate Kp. |
| 4–6 | Ordinary. Aurora possible, conditions unremarkable. |
| 2–4 | Poor. Something is substantially wrong — heavy cloud or a very quiet sky. |
| 1 | Not dark enough (hard gate), or no usable data. |

A score of exactly **1.00** is special: it means the darkness gate fired (sun
above −6°) or a factor was entirely unavailable. It is not "a very bad aurora
night" — it means the question does not apply.

## Calibration reference points

These are pinned in `tests/test_scoring.py`. They are the contract for how
conservative the model is.

| Scenario | aurora | sky | dark | moon | score |
|---|---|---|---|---|---|
| Everything perfect (unreachable in practice) | 1.00 | 1.00 | 1.00 | 1.00 | 10.00 |
| Polar night, Kp 5, region clear, no moon | 0.831 | 0.95 | 1.00 | 1.00 | 8.77 |
| Polar night, Kp 4, region clear, no moon | 0.672 | 0.95 | 1.00 | 1.00 | 7.82 |
| **Polar night, Kp 3, fully clear, no moon** | 0.525 | 1.00 | 1.00 | 1.00 | **7.04** |
| Polar night, Kp 3, mostly clear, thin moon | 0.525 | 0.85 | 1.00 | 0.97 | 6.35 |
| Polar night, Kp 2, clear region, no moon | 0.392 | 0.90 | 1.00 | 1.00 | 5.72 |
| Kp 3, clear, but only nautical twilight | 0.525 | 0.90 | 0.63 | 1.00 | 5.25 |
| Kp 2, half the region clouded | 0.392 | 0.55 | 1.00 | 1.00 | 4.48 |
| Kp 1, clear, bright moon high | 0.278 | 0.90 | 1.00 | 0.78 | 4.27 |
| Kp 1, broken cloud, full dark | 0.278 | 0.45 | 1.00 | 1.00 | 3.48 |
| Quiet (Kp 0) and overcast | 0.20 | 0.15 | 1.00 | 1.00 | 2.02 |
| Overcast, raining, twilight | 0.20 | 0.02 | 0.50 | 1.00 | 1.19 |
| Not dark at all | 0.831 | 1.00 | **0.00** | 1.00 | **1.00** |

Note the fourth-from-last row: the *September case*. Genuine Kp 3 activity under
a 90% clear sky still only reaches 5.25, purely because Tromsø does not get dark
enough that early in the season.

## What the score is not

**It is not a probability.** 7.33 does not mean 73%, or a 7.33-in-10 chance. It
is an ordinal-ish heuristic score on a calibrated scale. Do not convert it to a
percentage, and do not multiply or average scores across nights.

**It is not calibrated against observed sightings.** No historical verification
loop exists. The weights are documented, reasoned heuristics.

**Two decimal places are false precision.** The tool reports them for
reproducibility and testing, not because the underlying skill justifies them.
Round to whole numbers when communicating to a person.
