"""Sun and Moon geometry, via ``ephem``.

Everything here is local to a point and an instant; nothing needs the network.
The two outputs that matter downstream are a *darkness* factor and a *moon*
factor, both in 0..1.

At these latitudes the darkness term is not a refinement, it is the dominant
seasonal gate. Between roughly mid-May and late July the Sun never reaches
-6 deg at Tromso or Kiruna, and no combination of clear sky and geomagnetic
activity produces a visible aurora. The model must return "no window" for those
dates rather than a merely low score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import ephem

# Solar altitude boundaries, in degrees.
CIVIL_TWILIGHT = -6.0
NAUTICAL_TWILIGHT = -12.0
ASTRONOMICAL_TWILIGHT = -18.0

# Darkness at the nautical boundary. Aurora is genuinely observable in late
# nautical twilight at high latitude, so this is deliberately well above zero
# rather than the 0.7 a naive four-step ladder would give.
DARKNESS_AT_NAUTICAL = 0.55

# Below this, we treat the sky as unusable and gate the score to its floor.
MIN_USABLE_DARKNESS = 0.0


@dataclass(frozen=True, slots=True)
class SkyGeometry:
    """Sun and Moon geometry for one point at one instant."""

    sun_altitude_deg: float
    moon_altitude_deg: float
    moon_illumination: float  # 0..1 illuminated fraction
    darkness: float  # 0..1

    @property
    def is_dark_enough(self) -> bool:
        return self.darkness > MIN_USABLE_DARKNESS


def _observer(lat: float, lon: float, altitude_m: float, when: datetime) -> ephem.Observer:
    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.elevation = float(altitude_m)
    obs.date = ephem.Date(when.astimezone(timezone.utc).replace(tzinfo=None))
    # Aurora viewing is about the sky, not the refracted horizon; and pressure=0
    # disables ephem's refraction correction, which keeps twilight boundaries
    # matching the standard geometric definitions (-6/-12/-18 deg).
    obs.pressure = 0
    return obs


def darkness_from_sun_altitude(altitude_deg: float) -> float:
    """Map solar altitude to a 0..1 darkness factor.

    Piecewise-linear but continuous, so a score never jumps discontinuously as
    an hour crosses a twilight boundary.
    """
    if altitude_deg >= CIVIL_TWILIGHT:
        return 0.0
    if altitude_deg >= NAUTICAL_TWILIGHT:
        span = (CIVIL_TWILIGHT - altitude_deg) / (CIVIL_TWILIGHT - NAUTICAL_TWILIGHT)
        return DARKNESS_AT_NAUTICAL * span
    if altitude_deg >= ASTRONOMICAL_TWILIGHT:
        span = (NAUTICAL_TWILIGHT - altitude_deg) / (NAUTICAL_TWILIGHT - ASTRONOMICAL_TWILIGHT)
        return DARKNESS_AT_NAUTICAL + (1.0 - DARKNESS_AT_NAUTICAL) * span
    return 1.0


@lru_cache(maxsize=200_000)
def _geometry_cached(
    lat: float, lon: float, altitude_m: float, epoch: float
) -> tuple[float, float, float]:
    when = datetime.fromtimestamp(epoch, tz=timezone.utc)
    obs = _observer(lat, lon, altitude_m, when)
    sun = ephem.Sun()
    sun.compute(obs)
    moon = ephem.Moon()
    moon.compute(obs)
    return (
        math.degrees(float(sun.alt)),
        math.degrees(float(moon.alt)),
        float(moon.moon_phase),
    )


def sky_geometry(lat: float, lon: float, altitude_m: float, when: datetime) -> SkyGeometry:
    """Sun/Moon geometry and the derived darkness factor."""
    sun_alt, moon_alt, moon_illum = _geometry_cached(
        round(lat, 4), round(lon, 4), float(altitude_m), when.timestamp()
    )
    return SkyGeometry(
        sun_altitude_deg=sun_alt,
        moon_altitude_deg=moon_alt,
        moon_illumination=moon_illum,
        darkness=darkness_from_sun_altitude(sun_alt),
    )


def moon_factor(geometry: SkyGeometry, aurora_potential: float) -> float:
    """Moonlight penalty in 0..1, where 1 means "the Moon costs you nothing".

    Three things govern it:

    * A Moon below the horizon costs nothing at all, whatever its phase. This is
      why phase alone is a poor predictor - a full Moon that sets at 22:00 is
      irrelevant to a 01:00 display.
    * Between the horizon and ~30 deg the penalty ramps up; above that it
      saturates, since a high Moon is already flooding the whole sky.
    * A strong display punches through moonlight, so the penalty is scaled down
      as ``aurora_potential`` rises. A weak glow on the northern horizon is what
      a bright Moon actually destroys.
    """
    if geometry.moon_altitude_deg <= 0.0:
        return 1.0
    altitude_weight = min(1.0, geometry.moon_altitude_deg / 30.0)
    # Strength ranges from the full penalty for a weak aurora down to a third of
    # it for a strong one.
    strength = 0.30 * (1.0 - 0.65 * max(0.0, min(1.0, aurora_potential)))
    return 1.0 - strength * geometry.moon_illumination * altitude_weight
