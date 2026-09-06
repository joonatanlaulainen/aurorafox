"""Sun/Moon geometry, and the seasonal gate it imposes at these latitudes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aurorafox.astronomy import (
    ASTRONOMICAL_TWILIGHT,
    CIVIL_TWILIGHT,
    DARKNESS_AT_NAUTICAL,
    NAUTICAL_TWILIGHT,
    SkyGeometry,
    darkness_from_sun_altitude,
    moon_factor,
    sky_geometry,
)
from aurorafox.locations import all_cities, get_city

TROMSO = get_city("tromso")
REYKJAVIK = get_city("reykjavik")


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_darkness_ladder_is_continuous_and_monotonic():
    assert darkness_from_sun_altitude(0.0) == 0.0
    assert darkness_from_sun_altitude(CIVIL_TWILIGHT) == 0.0
    assert darkness_from_sun_altitude(NAUTICAL_TWILIGHT) == pytest.approx(
        DARKNESS_AT_NAUTICAL
    )
    assert darkness_from_sun_altitude(ASTRONOMICAL_TWILIGHT) == pytest.approx(1.0)
    assert darkness_from_sun_altitude(-40.0) == 1.0
    previous = -1.0
    for altitude in range(0, -400, -1):
        value = darkness_from_sun_altitude(altitude / 10.0)
        assert value >= previous
        previous = value


@pytest.mark.parametrize("city", [get_city("tromso"), get_city("kiruna")])
def test_midnight_sun_gates_summer_completely(city):
    """Late June is unusable at these latitudes, however clear and active."""
    for hour in range(24):
        geometry = sky_geometry(city.lat, city.lon, 0.0, at(f"2026-06-21T{hour:02d}:00"))
        assert geometry.darkness == 0.0
        assert not geometry.is_dark_enough


def test_polar_night_is_fully_dark_at_tromso():
    geometry = sky_geometry(TROMSO.lat, TROMSO.lon, 0.0, at("2026-12-21T22:00"))
    assert geometry.sun_altitude_deg < ASTRONOMICAL_TWILIGHT
    assert geometry.darkness == 1.0


def test_early_september_tromso_never_reaches_astronomical_night():
    """The reason a clear, active early-September night still is not a 9/10.

    Tromso in early September bottoms out in deep nautical twilight, several
    degrees short of true astronomical night, so the darkness factor caps the
    score no matter how good the aurora and cloud outlook are.
    """
    best = max(
        (
            sky_geometry(TROMSO.lat, TROMSO.lon, 0.0, at(f"2026-09-07T{hour:02d}:00"))
            for hour in range(24)
        ),
        key=lambda g: g.darkness,
    )
    assert ASTRONOMICAL_TWILIGHT < best.sun_altitude_deg < NAUTICAL_TWILIGHT
    assert 0.4 < best.darkness < 0.85


def test_reykjavik_regains_real_darkness_before_tromso_in_august():
    """Coming out of summer, the *lower*-latitude site darkens first.

    The intuition that "further north is always darker" is only true in
    midwinter; in August, Tromso's higher latitude keeps the sun nearer the
    horizon all night. Compared at each site's darkest hour, not a shared UTC
    instant, since their longitudes differ by nearly three hours.
    """

    def darkest(city) -> float:
        return max(
            sky_geometry(city.lat, city.lon, 0.0, at(f"2026-08-20T{hour:02d}:00")).darkness
            for hour in range(24)
        )

    assert darkest(REYKJAVIK) > darkest(TROMSO)


def _geometry(moon_alt: float, illum: float) -> SkyGeometry:
    return SkyGeometry(
        sun_altitude_deg=-20.0,
        moon_altitude_deg=moon_alt,
        moon_illumination=illum,
        darkness=1.0,
    )


def test_moon_below_horizon_costs_nothing_at_any_phase():
    assert moon_factor(_geometry(-1.0, 1.0), 0.5) == 1.0
    assert moon_factor(_geometry(-40.0, 1.0), 0.5) == 1.0


def test_moon_penalty_grows_with_phase_and_altitude():
    low_phase = moon_factor(_geometry(40.0, 0.2), 0.5)
    high_phase = moon_factor(_geometry(40.0, 1.0), 0.5)
    assert high_phase < low_phase < 1.0

    low_altitude = moon_factor(_geometry(5.0, 1.0), 0.5)
    high_altitude = moon_factor(_geometry(45.0, 1.0), 0.5)
    assert high_altitude < low_altitude


def test_strong_aurora_punches_through_moonlight():
    """A full Moon should mark down a weak glow far more than a strong display."""
    full_moon = _geometry(45.0, 1.0)
    weak = moon_factor(full_moon, 0.2)
    strong = moon_factor(full_moon, 1.0)
    assert weak < strong < 1.0
    # And the penalty stays moderate: never more than ~30% even at its worst.
    assert weak > 0.68


def test_moon_illumination_tracks_known_full_moon():
    """2026-01-03 is a full Moon; illumination should be near unity."""
    geometry = sky_geometry(TROMSO.lat, TROMSO.lon, 0.0, at("2026-01-03T12:00"))
    assert geometry.moon_illumination > 0.97


@pytest.mark.parametrize("city", all_cities(), ids=lambda c: c.key)
def test_every_city_has_full_darkness_at_midwinter(city):
    geometry = sky_geometry(city.lat, city.lon, 0.0, at("2026-01-15T23:00"))
    assert geometry.darkness == 1.0
