"""Combine aurora, sky, darkness and moon into a conservative 1-10 score.

The core expression is unremarkable::

    raw = aurora * sky * darkness * moon

What makes the output trustworthy is what happens either side of it.

**Confidence is applied as a shrink, not a multiply.** Each of the two forecast
factors is pulled toward a pessimistic prior in proportion to how little the
data actually supports it::

    adjusted = prior + confidence * (value - prior)

A plain multiply would make an uncertain day-5 signal merely *smaller*, which
still lets a spuriously exciting one clear a threshold once the other factors
are high. Shrinking pulls it toward "ordinary" instead, which is the honest
statement: at five days out we do not know, and a forecast that does not know
should not be raising an alert.

**Aurora and sky confidence decay at different rates**, because the underlying
products do. MET's cloud forecast degrades gracefully across five days. NOAA's
Kp forecast simply *stops* at about 72 hours, after which the only signal is a
daily maximum from a 27-day recurrence table that may be a week old. Treating
those two as a single "forecast confidence" would badly misstate days 4-5.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..astronomy import SkyGeometry, moon_factor, sky_geometry
from ..geo import clamp
from ..locations import City
from .aurora import AuroraFactors
from .sky import ClusterSky

# Priors: what an unremarkable night looks like. Confidence shrinks toward these.
PRIOR_AURORA = 0.40
PRIOR_SKY = 0.45

# Maps raw 0..1 onto 1..10. Chosen so that clearing 7.0 requires raw >= ~0.535,
# i.e. genuine geomagnetic activity AND a genuinely clear region AND darkness.
# Pinned by the calibration table in tests/test_scoring.py - change it there and
# the tests will tell you exactly which scenarios moved.
SCORE_GAMMA = 0.62

# Days 4-5 have no real aurora forecast behind them, so they are not permitted
# to raise an alert however good they look. They surface on the clear-sky
# watchlist instead.
LONG_RANGE_SCORE_CAP = 6.0
LONG_RANGE_HOURS = 72.0

# Interpolated (natively 6-hourly) samples lose a little further confidence.
INTERPOLATION_CONFIDENCE = 0.90


@dataclass(frozen=True, slots=True)
class HorizonTier:
    """Forecast skill for a lead time, tracked separately per data source."""

    name: str
    max_lead_hours: float
    aurora_confidence: float
    sky_confidence: float
    note: str


TIERS: tuple[HorizonTier, ...] = (
    HorizonTier(
        "0-12 h", 12.0, 1.00, 1.00,
        "Kp forecast sharpened by the OVATION nowcast and live solar wind",
    ),
    HorizonTier(
        "12-24 h", 24.0, 0.90, 0.95,
        "3-hourly Kp forecast; MET still at native hourly resolution",
    ),
    HorizonTier(
        "24-48 h", 48.0, 0.80, 0.85,
        "3-hourly Kp forecast; cloud detail starting to soften",
    ),
    HorizonTier(
        "48-72 h", 72.0, 0.65, 0.75,
        "Edge of the Kp product's range",
    ),
    HorizonTier(
        "72-120 h", 1e9, 0.40, 0.60,
        "No Kp forecast exists this far out - only a daily maximum from the "
        "27-day recurrence outlook. Score capped, alerting disabled.",
    ),
)


def tier_for(lead_hours: float) -> HorizonTier:
    for tier in TIERS:
        if lead_hours <= tier.max_lead_hours:
            return tier
    return TIERS[-1]


def shrink(value: float, confidence: float, prior: float) -> float:
    return prior + confidence * (value - prior)


def to_score(raw: float) -> float:
    return 1.0 + 9.0 * (clamp(raw) ** SCORE_GAMMA)


@dataclass(frozen=True, slots=True)
class HourScore:
    """A single hour at a single city, with every input kept visible."""

    time: datetime
    city_key: str
    score: float
    raw: float
    aurora: AuroraFactors
    aurora_adjusted: float
    cluster: ClusterSky | None
    sky_adjusted: float
    geometry: SkyGeometry
    moon: float
    tier: HorizonTier
    lead_hours: float
    capped: bool
    clear_point_count: int
    clear_span_km: float

    @property
    def sky(self) -> float:
        return self.cluster.sky if self.cluster else 0.0

    @property
    def limiting_factor(self) -> str:
        """Which input is holding this hour back - the useful part on a bad night."""
        if self.geometry.darkness <= 0.0:
            return "not dark (sun above -6 deg)"
        candidates = {
            "darkness": self.geometry.darkness,
            "cloud": self.sky_adjusted,
            "aurora activity": self.aurora_adjusted,
            "moonlight": self.moon,
        }
        name = min(candidates, key=lambda k: candidates[k])
        if candidates[name] > 0.75:
            return "nothing in particular - all factors favourable"
        if name == "cloud" and self.cluster is None:
            return "cloud (no coherent clear region found)"
        return name


def score_hour(
    when: datetime,
    now: datetime,
    city: City,
    aurora: AuroraFactors,
    cluster: ClusterSky | None,
    *,
    clear_point_count: int = 0,
    clear_span_km: float = 0.0,
    any_interpolated: bool = False,
) -> HourScore:
    """Assemble one hour's score from its parts."""
    lead_hours = (when - now).total_seconds() / 3600.0
    tier = tier_for(lead_hours)

    geometry = sky_geometry(city.lat, city.lon, 0.0, when)
    moon = moon_factor(geometry, aurora.potential)

    sky_confidence = tier.sky_confidence
    if any_interpolated:
        sky_confidence *= INTERPOLATION_CONFIDENCE

    aurora_adjusted = clamp(shrink(aurora.potential, tier.aurora_confidence, PRIOR_AURORA))
    sky_value = cluster.sky if cluster is not None else 0.0
    sky_adjusted = clamp(shrink(sky_value, sky_confidence, PRIOR_SKY))

    # No coherent clear region means no eligible place to stand. Do not let the
    # shrink toward the prior invent one.
    if cluster is None:
        sky_adjusted = min(sky_adjusted, 0.25)

    raw = aurora_adjusted * sky_adjusted * geometry.darkness * moon
    score = to_score(raw)

    capped = False
    if lead_hours > LONG_RANGE_HOURS and score > LONG_RANGE_SCORE_CAP:
        score = LONG_RANGE_SCORE_CAP
        capped = True

    if geometry.darkness <= 0.0:
        score = 1.0
        capped = False

    return HourScore(
        time=when,
        city_key=city.key,
        score=round(score, 2),
        raw=raw,
        aurora=aurora,
        aurora_adjusted=aurora_adjusted,
        cluster=cluster,
        sky_adjusted=sky_adjusted,
        geometry=geometry,
        moon=moon,
        tier=tier,
        lead_hours=lead_hours,
        capped=capped,
        clear_point_count=clear_point_count,
        clear_span_km=clear_span_km,
    )


def night_key(when: datetime, city: City) -> str:
    """Label an hour with the night it belongs to (the date the evening starts).

    Hours before local noon belong to the night that began the previous evening,
    so a 02:00 peak is reported under the night you would set out on.
    """
    local = when.astimezone(ZoneInfo(city.timezone))
    if local.hour < 12:
        local -= timedelta(days=1)
    return local.date().isoformat()
