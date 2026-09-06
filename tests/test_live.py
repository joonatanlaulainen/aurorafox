"""Smoke tests against the real APIs.

Deselected by default (``-m "not live"``) so the normal suite stays offline and
deterministic. Run them when you want to know whether an upstream product has
changed shape under you - which is the failure mode that actually bites here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aurorafox import run_aurora_watch
from aurorafox.locations import get_city
from aurorafox.sources import swpc

pytestmark = pytest.mark.live


def test_kp_forecast_still_stops_around_three_days():
    """If SWPC ever extends this product, the horizon tiers should be revisited."""
    forecast = swpc.fetch_kp_forecast()
    now = datetime.now(timezone.utc)
    assert forecast.horizon_end is not None
    lead = (forecast.horizon_end - now).total_seconds() / 3600.0
    assert 24 < lead < 120, f"Kp forecast horizon moved to {lead:.0f} h"


def test_ovation_is_still_a_short_range_nowcast():
    nowcast = swpc.fetch_ovation()
    lead = (nowcast.forecast_time - datetime.now(timezone.utc)).total_seconds() / 3600.0
    assert -1 < lead < 3, f"OVATION forecast time is {lead:.1f} h out"
    assert nowcast.probability(69.65, 18.96) is not None


def test_metno_still_serves_cloud_layers_for_every_city():
    from aurorafox.sources.metno import fetch_point

    for key in ("tromso", "kiruna", "rovaniemi", "reykjavik"):
        city = get_city(key)
        forecast = fetch_point(city.points[0])
        first = forecast.samples[min(forecast.samples)]
        assert first.cloud_low is not None, key
        assert first.cloud_medium is not None, key
        assert first.cloud_high is not None, key


def test_metno_still_drops_fog_at_long_range():
    """Documented behaviour the sky model compensates for. If this ever starts
    failing, the humidity proxy can be retired."""
    from aurorafox.sources.metno import fetch_point

    forecast = fetch_point(get_city("tromso").points[0])
    far = datetime.now(timezone.utc) + timedelta(days=7)
    sample = forecast.at(far.replace(minute=0, second=0, microsecond=0))
    assert sample is not None
    assert sample.fog is None


def test_full_run_completes_and_is_self_consistent():
    watch = run_aurora_watch(days=5)
    assert len(watch.cities) == 4
    for outlook in watch.cities:
        assert outlook.points_used >= 10, outlook.city.key
        assert len(outlook.nights) >= 5
        for night in outlook.nights:
            assert 1.0 <= night.score <= 10.0
            if night.qualifies:
                assert night.window_start is not None
                assert night.score >= watch.threshold
    for alert in watch.alerts:
        assert alert.qualifies
        assert alert.peak.lead_hours <= 72.0, "days 4-5 must never alert"


def test_summer_run_finds_nothing_anywhere():
    """The darkness gate, verified end to end against live data."""
    watch = run_aurora_watch(days=5, now=datetime(2027, 6, 20, 12, tzinfo=timezone.utc))
    assert watch.alerts == []
    for outlook in watch.cities:
        # dark_hours, not just the score: this asserts the *darkness gate* fired,
        # rather than passing vacuously because no cloud forecast reaches 2027.
        assert all(night.dark_hours == 0 for night in outlook.nights), outlook.city.key
        assert all(night.score == 1.0 for night in outlook.nights), outlook.city.key
