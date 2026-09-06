"""Aurora potential A(t, site) in 0..1.

The design note this implements says that at Tromso, Kp alone is not a
sufficient aurora metric. That is taken literally here: the model is built
around **where the auroral oval sits relative to the site**, not around Kp as a
scalar "how good is tonight" number.

Why that matters. The oval is a ring around the geomagnetic pole whose
equatorward edge marches towards the equator as activity rises. A site is well
placed when the oval is overhead or just to its north. Tromso, at 66.6 deg
corrected geomagnetic latitude, sits under the oval during *quiet* conditions -
so a big storm can push the oval **past** it, leaving Tromso inside the polar
cap with the aurora to its south and often more diffuse overhead. A model of the
form ``score ~ Kp`` gets that exactly backwards, and would send you north on
precisely the nights you should be driving south.

So potential here is a *band response*: it peaks when the site is in or just
equatorward of the oval, and falls off in both directions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from ..geo import clamp
from ..locations import City
from ..sources.swpc import (
    KpForecast,
    OvationNowcast,
    Outlook27Day,
    SolarWind,
    SpaceWeatherAlerts,
    solar_wind_boost,
)

# Equatorward edge of the oval in corrected geomagnetic latitude, midnight
# sector: edge ~= 66.5 - 2.0 * Kp. A standard first-order relation; good to a
# degree or two over Kp 0-7, which is the range that matters here.
OVAL_EDGE_AT_KP0 = 66.5
OVAL_EDGE_PER_KP = 2.0

# The oval also thickens substantially with activity - a storm oval is far
# wider than a quiet one, which is why a big storm lights up a huge swathe of
# latitude rather than sweeping a narrow ring past you.
OVAL_WIDTH_BASE = 4.0
OVAL_WIDTH_PER_KP = 1.2

# Falloff scales in degrees, measured from the *edge of the band*, for a site
# equatorward of the oval (aurora to the north, still very much visible) versus
# poleward of it (inside the polar cap, aurora to the south).
FALLOFF_EQUATORWARD = 5.0
FALLOFF_POLEWARD = 4.5

# Intrinsic brightness and dynamism of the display, given that the geometry is
# already favourable: a quiet arc overhead is not a substorm.
#
# Deliberately non-linear in Kp. An earlier linear form (0.35 + 0.13*Kp) scored a
# geomagnetically dead Kp 0 night at 5.5/10 under a clear winter sky, and let
# Kp 2 clear the alert threshold. Both are too generous - quiet-time aurora at
# these latitudes is a faint static arc, while auroral power rises far faster
# than Kp itself does.
#
# Calibrated so that at Tromso, under a fully clear sky in full darkness with no
# moon, Kp 3 lands just on the 7.0 threshold and Kp 4 clears it decisively. The
# scale that falls out is close to one point per Kp step (Kp 1 -> 5.1,
# 2 -> 6.0, 3 -> 7.0, 4 -> 8.0, 5 -> 9.0, 6 -> 10.0), which is worth preserving
# if you retune it. Pinned by tests/test_scoring.py.
INTENSITY_FLOOR = 0.20
INTENSITY_REFERENCE_KP = 6.0
INTENSITY_EXPONENT = 1.3

# The 27-day outlook publishes each day's *largest* Kp. Typical conditions
# during any given hour are meaningfully below that peak.
OUTLOOK_PEAK_DISCOUNT = 0.7


@dataclass(frozen=True, slots=True)
class AuroraFactors:
    """A potential value with the reasoning that produced it."""

    potential: float
    kp: float | None
    kp_source: str
    site_cgm: float
    oval_edge_cgm: float | None
    oval_poleward_cgm: float | None
    site_offset_deg: float | None  # site CGM lat minus oval centre
    band_response: float
    mlt_weight: float
    ovation_percent: float | None
    solar_wind_boost: float
    storm_floor: float

    @property
    def site_position(self) -> str:
        """Where the site sits relative to the oval band: inside, or which side."""
        if self.oval_edge_cgm is None or self.oval_poleward_cgm is None:
            return "unknown"
        if self.site_cgm < self.oval_edge_cgm:
            return "equatorward"
        if self.site_cgm > self.oval_poleward_cgm:
            return "poleward"
        return "inside"

    @property
    def geometry_note(self) -> str:
        position = self.site_position
        if position == "unknown":
            return "no Kp available"
        if position == "poleward":
            gap = self.site_cgm - (self.oval_poleward_cgm or 0.0)
            return (
                f"oval has expanded {gap:.1f} deg south past you - look south, "
                "and expect more diffuse overhead"
            )
        if position == "equatorward":
            gap = (self.oval_edge_cgm or 0.0) - self.site_cgm
            if gap > 3.0:
                return f"oval {gap:.1f} deg to your north - at best a low glow on the horizon"
            return f"oval just {gap:.1f} deg north - aurora low in the northern sky"
        return "oval overhead - well placed"


def aurora_intensity(kp: float) -> float:
    """Intrinsic display intensity in 0..1, independent of where the site sits.

    Saturates at :data:`INTENSITY_REFERENCE_KP`: past a strong storm the limit on
    what you see stops being available power and starts being geometry, which the
    band response already handles.
    """
    reach = (min(1.0, max(0.0, kp) / INTENSITY_REFERENCE_KP)) ** INTENSITY_EXPONENT
    return clamp(INTENSITY_FLOOR + (1.0 - INTENSITY_FLOOR) * reach)


def oval_edge_cgm(kp: float) -> float:
    """Equatorward edge of the auroral oval, in corrected geomagnetic latitude."""
    return OVAL_EDGE_AT_KP0 - OVAL_EDGE_PER_KP * kp


def oval_width(kp: float) -> float:
    return OVAL_WIDTH_BASE + OVAL_WIDTH_PER_KP * kp


def band_response(site_cgm: float, kp: float) -> tuple[float, float]:
    """How well the site sits relative to the oval.

    Returns ``(response, offset)`` where ``offset`` is the site's geomagnetic
    latitude minus the oval centre - negative means the oval is to your north,
    positive means it has expanded south past you.

    The response is flat at 1.0 anywhere *inside* the band and decays with
    distance from the nearer edge. That flat interior is the point: over the
    Kp range where the oval actually covers these sites, geometry stops
    discriminating between them and the intensity term takes over.
    """
    edge = oval_edge_cgm(kp)
    width = oval_width(kp)
    centre = edge + width / 2.0
    offset = site_cgm - centre

    if site_cgm < edge:
        distance, scale = edge - site_cgm, FALLOFF_EQUATORWARD
    elif site_cgm > edge + width:
        distance, scale = site_cgm - (edge + width), FALLOFF_POLEWARD
    else:
        return 1.0, offset
    return math.exp(-((distance / scale) ** 2)), offset


def mlt_weight(when: datetime, city: City) -> float:
    """Weight for proximity to magnetic midnight, where substorms concentrate."""
    hour = when.astimezone(timezone.utc).hour + when.minute / 60.0
    delta = (hour - city.magnetic_midnight_utc + 12.0) % 24.0 - 12.0
    distance = abs(delta)
    if distance <= 2.5:
        return 1.0
    return max(0.45, 1.0 - 0.11 * (distance - 2.5))


def _kp_for(
    when: datetime,
    now: datetime,
    kp_forecast: KpForecast | None,
    outlook: Outlook27Day | None,
) -> tuple[float | None, str]:
    """Kp for an instant, preferring the 3-hourly product while it reaches."""
    if kp_forecast is not None:
        value = kp_forecast.at(when)
        if value is not None:
            observed = when <= now
            return value, "observed Kp" if observed else "SWPC 3-hourly Kp forecast"
    if outlook is not None:
        peak = outlook.at(when)
        if peak is not None:
            # Weak upper bound only: this is a daily maximum from coronal-hole
            # recurrence, issued up to a week earlier.
            return max(0.0, peak - OUTLOOK_PEAK_DISCOUNT), "27-day outlook (daily max Kp)"
    return None, "unavailable"


def aurora_potential(
    when: datetime,
    now: datetime,
    city: City,
    *,
    kp_forecast: KpForecast | None = None,
    outlook: Outlook27Day | None = None,
    ovation: OvationNowcast | None = None,
    solar_wind: SolarWind | None = None,
    alerts: SpaceWeatherAlerts | None = None,
) -> AuroraFactors:
    """Aurora potential at a city for one instant."""
    kp, kp_source = _kp_for(when, now, kp_forecast, outlook)
    lead_hours = (when - now).total_seconds() / 3600.0

    if kp is None:
        response, offset, edge, poleward = 0.0, None, None, None
        base = 0.0
    else:
        response, offset = band_response(city.cgm_latitude, kp)
        edge = oval_edge_cgm(kp)
        poleward = edge + oval_width(kp)
        base = aurora_intensity(kp) * response

    weight = mlt_weight(when, city)
    potential = base * weight

    # Short-horizon sharpening. Confined to the window where the nowcast and
    # propagated solar wind are physically meaningful - past a few hours the
    # solar wind now at the magnetopause tells you nothing about tomorrow.
    wind_boost = 0.0
    if solar_wind is not None and 0.0 <= lead_hours <= 3.0:
        wind_boost = solar_wind_boost(solar_wind)
        potential = clamp(potential * (1.0 + 0.45 * wind_boost))

    ovation_percent: float | None = None
    if ovation is not None and 0.0 <= lead_hours <= 3.0:
        ovation_percent = ovation.probability(city.lat, city.lon)
        if ovation_percent is not None:
            # OVATION is a genuine observation-driven nowcast, so it earns real
            # weight close in and none at all past three hours.
            trust = 0.5 if lead_hours <= 1.5 else 0.25
            ovation_term = clamp(ovation_percent / 60.0) * weight
            potential = potential * (1.0 - trust) + ovation_term * trust

    # An active storm watch raises the floor on the affected period rather than
    # scaling the estimate: a G-level watch is a statement about what *could*
    # happen, and should not multiply an already-optimistic geometry term.
    storm_floor = 0.0
    if alerts is not None and lead_hours <= 48.0:
        level = alerts.max_watch_level(now)
        if level:
            storm_floor = min(0.75, 0.30 + 0.10 * level) * weight * (
                response if kp is not None else 1.0
            )
            potential = max(potential, storm_floor)

    return AuroraFactors(
        potential=clamp(potential),
        kp=kp,
        kp_source=kp_source,
        site_cgm=city.cgm_latitude,
        oval_edge_cgm=edge,
        oval_poleward_cgm=poleward,
        site_offset_deg=offset,
        band_response=response,
        mlt_weight=weight,
        ovation_percent=ovation_percent,
        solar_wind_boost=wind_boost,
        storm_floor=storm_floor,
    )
