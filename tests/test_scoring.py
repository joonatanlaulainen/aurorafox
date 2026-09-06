"""Scoring behaviour, pinned by a table of named reference scenarios.

The calibration table below is the contract for how conservative this model is.
To make the estimator harsher or more generous, change SCORE_GAMMA, the priors
or the tier confidences, then read off which scenarios moved. That is a far more
legible way to tune it than adjusting magic numbers and hoping.
"""

from __future__ import annotations

from itertools import pairwise
from datetime import datetime, timedelta, timezone

import pytest

from aurorafox.locations import get_city
from aurorafox.scoring.aurora import (
    aurora_intensity,
    aurora_potential,
    band_response,
    mlt_weight,
    oval_edge_cgm,
    oval_width,
)
from aurorafox.scoring.combine import (
    LONG_RANGE_SCORE_CAP,
    PRIOR_AURORA,
    PRIOR_SKY,
    shrink,
    tier_for,
    to_score,
)
from aurorafox.sources.swpc import KpForecast

TROMSO = get_city("tromso")
KIRUNA = get_city("kiruna")
ROVANIEMI = get_city("rovaniemi")


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# The calibration table: (name, aurora, sky, darkness, moon, expected score)
# ---------------------------------------------------------------------------

CALIBRATION = [
    #  name                                        aurora  sky  dark  moon  score
    ("everything perfect (unreachable in practice)", 1.00, 1.00, 1.00, 1.00, 10.00),
    ("polar night, Kp 5, region clear, no moon", 0.831, 0.95, 1.00, 1.00, 8.77),
    ("polar night, Kp 4, region clear, no moon", 0.672, 0.95, 1.00, 1.00, 7.82),
    # The anchor the whole scale is tuned to: Kp 3 under a fully clear, fully
    # dark, moonless sky at Tromso lands just on the alert threshold.
    ("polar night, Kp 3, fully clear, no moon", 0.525, 1.00, 1.00, 1.00, 7.04),
    ("polar night, Kp 3, mostly clear, thin moon", 0.525, 0.85, 1.00, 0.97, 6.35),
    ("polar night, Kp 2, clear region, no moon", 0.392, 0.90, 1.00, 1.00, 5.72),
    # The September case: genuine activity and a clear sky, held well under the
    # threshold purely because Tromso never gets properly dark that early.
    ("Kp 3, clear, but only nautical twilight", 0.525, 0.90, 0.63, 1.00, 5.25),
    ("Kp 2, half the region clouded", 0.392, 0.55, 1.00, 1.00, 4.48),
    ("Kp 1, clear, bright moon high", 0.278, 0.90, 1.00, 0.78, 4.27),
    ("Kp 1, broken cloud, full dark", 0.278, 0.45, 1.00, 1.00, 3.48),
    ("quiet (Kp 0) and overcast", 0.20, 0.15, 1.00, 1.00, 2.02),
    ("overcast, raining, twilight", 0.20, 0.02, 0.50, 1.00, 1.19),
    ("not dark at all", 0.831, 1.00, 0.00, 1.00, 1.00),
]


@pytest.mark.parametrize(
    "name,aurora,sky,darkness,moon,expected",
    CALIBRATION,
    ids=[row[0] for row in CALIBRATION],
)
def test_calibration_table(name, aurora, sky, darkness, moon, expected):
    """These are the fixed points the whole 1-10 scale is anchored to."""
    assert to_score(aurora * sky * darkness * moon) == pytest.approx(expected, abs=0.02)


def test_tromso_threshold_anchor_is_kp_three_under_a_perfect_sky():
    """The calibration this model is tuned to.

    At Tromso, a fully clear region in full darkness with no moon should land
    *just* on the 7.0 alert threshold at Kp 3, and clear it decisively at Kp 4.
    Everything else about the aurora curve follows from these two points.
    """
    response, _ = band_response(TROMSO.cgm_latitude, 3)
    assert response == pytest.approx(1.0), "Tromso must be inside the oval at Kp 3"

    kp3 = to_score(aurora_intensity(3) * 1.0 * 1.0 * 1.0)
    kp4 = to_score(aurora_intensity(4) * 1.0 * 1.0 * 1.0)
    assert 7.0 <= kp3 <= 7.15, kp3
    assert kp4 >= 8.0, kp4


def test_kp_two_no_longer_alerts_on_a_clear_night():
    """The over-scoring that prompted this calibration.

    Under the previous linear intensity curve, Kp 2 with a clear sky scored 7.4
    and raised an alert, and a geomagnetically dead Kp 0 night still scored 5.5.
    """
    assert to_score(aurora_intensity(2) * 1.0 * 1.0 * 1.0) < 7.0
    assert to_score(aurora_intensity(0) * 1.0 * 1.0 * 1.0) < 5.0


def test_intensity_curve_gives_roughly_one_point_per_kp_step():
    """An emergent property worth preserving if the curve is ever retuned."""
    scores = [to_score(aurora_intensity(kp)) for kp in range(1, 7)]
    steps = [b - a for a, b in pairwise(scores)]
    for step in steps:
        assert 0.9 < step < 1.1, scores


def test_intensity_is_monotonic_and_saturates():
    previous = -1.0
    for tenth in range(0, 100):
        value = aurora_intensity(tenth / 10.0)
        assert value >= previous
        previous = value
    assert aurora_intensity(0) == pytest.approx(0.20)
    assert aurora_intensity(6) == pytest.approx(1.0)
    assert aurora_intensity(9) == pytest.approx(1.0)


def test_threshold_of_seven_demands_all_factors_together():
    """A 7 must not be reachable by one excellent factor carrying weak ones."""
    # Superb aurora, but the region is half clouded: not an alert.
    assert to_score(1.00 * 0.50 * 1.00 * 1.00) < 7.0
    # Pristine sky, but nothing happening geomagnetically: not an alert.
    assert to_score(aurora_intensity(1) * 1.00 * 1.00 * 1.00) < 7.0
    # Genuine activity and a genuinely clear region: an alert.
    assert to_score(aurora_intensity(4) * 0.90 * 1.00 * 0.97) >= 7.0


def test_score_is_monotonic_in_every_factor():
    base = 0.6
    for index in range(4):
        factors = [base] * 4
        low = to_score(_product(factors))
        factors[index] = base + 0.1
        assert to_score(_product(factors)) > low


def _product(values):
    result = 1.0
    for value in values:
        result *= value
    return result


# ---------------------------------------------------------------------------
# Oval geometry
# ---------------------------------------------------------------------------


def test_oval_marches_south_and_widens_with_activity():
    assert oval_edge_cgm(5) < oval_edge_cgm(0)
    assert oval_width(5) > oval_width(0)


def test_quiet_conditions_favour_tromso_over_rovaniemi():
    """At Kp 0 only the highest-latitude site is under the oval."""
    tromso, _ = band_response(TROMSO.cgm_latitude, 0)
    rovaniemi, _ = band_response(ROVANIEMI.cgm_latitude, 0)
    assert tromso > rovaniemi
    assert tromso == pytest.approx(1.0)


def test_moderate_activity_covers_every_site_equally():
    """Between Kp 2 and 5 the oval spans all four; geometry stops discriminating."""
    for kp in (2, 3, 4, 5):
        for city in (TROMSO, KIRUNA, ROVANIEMI, get_city("reykjavik")):
            response, _ = band_response(city.cgm_latitude, kp)
            assert response > 0.99, (city.key, kp, response)


def test_extreme_storms_push_the_oval_past_tromso():
    """The polar-cap effect: Tromso degrades at extreme Kp while others do not.

    This is the behaviour a naive `score ~ Kp` model gets wrong, and the reason
    corrected geomagnetic latitude is carried per city. Note the claim is about
    where Tromso *peaks*, not that a great storm is bad there - at Kp 9 the sky
    is still lit up, just increasingly to the south and increasingly less well
    placed than sites further from the pole.
    """
    tromso_kp9, _ = band_response(TROMSO.cgm_latitude, 9)
    rovaniemi_kp9, _ = band_response(ROVANIEMI.cgm_latitude, 9)
    assert tromso_kp9 < 0.7
    assert rovaniemi_kp9 == pytest.approx(1.0)

    def potential(city, kp):
        response, _ = band_response(city.cgm_latitude, kp)
        return response * aurora_intensity(kp)

    # Tromso's potential peaks at moderate-to-high activity and falls away
    # beyond it, ending at Kp 9 back around its Kp 3 level.
    curve = [potential(TROMSO, kp) for kp in range(10)]
    assert curve.index(max(curve)) == 6, curve
    assert potential(TROMSO, 9) < potential(TROMSO, 6)
    assert potential(TROMSO, 9) == pytest.approx(potential(TROMSO, 3), abs=0.1)

    # Rovaniemi, further from the pole, plateaus at the maximum instead of
    # falling away - the oval never passes it.
    assert potential(ROVANIEMI, 9) == pytest.approx(1.0)
    assert potential(ROVANIEMI, 9) >= potential(ROVANIEMI, 6)
    # So in a severe storm Tromso is materially the worse bet of the two.
    assert potential(TROMSO, 9) < 0.65 * potential(ROVANIEMI, 9)


def test_site_position_reported_correctly():
    kp = _kp_forecast_at(3.0)
    factors = aurora_potential(at("2026-12-21T21:30"), at("2026-12-21T18:00"), TROMSO,
                               kp_forecast=kp)
    assert factors.site_position == "inside"

    kp = _kp_forecast_at(9.0)
    factors = aurora_potential(at("2026-12-21T21:30"), at("2026-12-21T18:00"), TROMSO,
                               kp_forecast=kp)
    assert factors.site_position == "poleward"
    assert "south past you" in factors.geometry_note


# ---------------------------------------------------------------------------
# Magnetic local time
# ---------------------------------------------------------------------------


def test_magnetic_midnight_is_the_peak():
    midnight = at("2026-12-21T21:30")
    assert mlt_weight(midnight, TROMSO) == pytest.approx(1.0)
    assert mlt_weight(midnight - timedelta(hours=6), TROMSO) < 0.75
    assert mlt_weight(midnight + timedelta(hours=6), TROMSO) < 0.75


def test_mlt_weight_never_collapses_to_zero():
    """Aurora at noon MLT is unlikely, not impossible - the floor keeps it honest."""
    for hour in range(24):
        assert mlt_weight(at(f"2026-12-21T{hour:02d}:00"), TROMSO) >= 0.45


# ---------------------------------------------------------------------------
# Horizon tiers and the long-range cap
# ---------------------------------------------------------------------------


def _kp_forecast_at(kp: float) -> KpForecast:
    start = at("2026-12-20T00:00")
    entries = [
        (start + timedelta(hours=3 * i), kp, i > 4) for i in range(60)
    ]
    return KpForecast(entries=entries, fetched_at=start)


def test_tier_boundaries():
    assert tier_for(1).name == "0-12 h"
    assert tier_for(12).name == "0-12 h"
    assert tier_for(13).name == "12-24 h"
    assert tier_for(47).name == "24-48 h"
    assert tier_for(70).name == "48-72 h"
    assert tier_for(100).name == "72-120 h"


def test_aurora_confidence_decays_faster_than_sky_confidence():
    """The products degrade at different rates, so the tiers must too."""
    for tier_hours in (20, 40, 70, 110):
        tier = tier_for(tier_hours)
        assert tier.aurora_confidence <= tier.sky_confidence


def test_shrink_pulls_toward_the_prior_from_both_directions():
    assert shrink(0.9, 0.4, PRIOR_AURORA) < 0.9
    assert shrink(0.9, 0.4, PRIOR_AURORA) > PRIOR_AURORA
    assert shrink(0.1, 0.4, PRIOR_SKY) > 0.1
    assert shrink(0.5, 1.0, PRIOR_SKY) == pytest.approx(0.5)


def test_same_conditions_score_lower_further_out():
    """The central conservatism property, stated directly."""
    aurora, sky = 0.85, 0.90
    scores = []
    for lead in (6, 20, 40, 70, 100):
        tier = tier_for(lead)
        scores.append(
            to_score(
                shrink(aurora, tier.aurora_confidence, PRIOR_AURORA)
                * shrink(sky, tier.sky_confidence, PRIOR_SKY)
            )
        )
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 8.5
    assert scores[-1] < LONG_RANGE_SCORE_CAP + 1.0


def test_an_excellent_looking_day_five_cannot_reach_the_threshold():
    """Days 4-5 have no aurora forecast behind them, so they must not alert."""
    tier = tier_for(110)
    best_case = to_score(
        shrink(1.0, tier.aurora_confidence, PRIOR_AURORA)
        * shrink(1.0, tier.sky_confidence, PRIOR_SKY)
    )
    assert best_case < 7.0
