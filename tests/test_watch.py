"""End-to-end behaviour of run_aurora_watch(), with every source stubbed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aurorafox import run_aurora_watch
from aurorafox.locations import get_city
from aurorafox.scoring.combine import LONG_RANGE_SCORE_CAP
from aurorafox.sources import swpc
from aurorafox.sources.http import SourceError
from aurorafox.sources.metno import PointForecast, WeatherSample
from aurorafox.watch import MIN_WINDOW_HOURS


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


MIDWINTER = at("2026-12-21T18:00")
MIDSUMMER = at("2026-06-21T18:00")


def make_forecast(point, *, cloud_low: float, hours: int = 200):
    """A uniform forecast covering every reference time the tests use.

    Uniform on purpose: with cloud held constant at every point and hour, any
    variation in the resulting scores has to come from the model - the horizon
    tiers, darkness, or the moon - and not from the weather.
    """
    samples = {}
    for start in (MIDSUMMER, MIDWINTER):
        base = start.replace(minute=0, second=0, microsecond=0)
        for offset in range(hours):
            when = base + timedelta(hours=offset)
            samples[when] = WeatherSample(
                time=when,
                cloud_total=cloud_low,
                cloud_low=cloud_low,
                cloud_medium=0.0,
                cloud_high=0.0,
                fog=0.0,
                relative_humidity=70.0,
                precipitation_mm=0.0,
                native_step_hours=1.0,
            )
    return PointForecast(point=point, samples=samples, updated_at=MIDWINTER, from_cache=False)


@pytest.fixture
def stub_sources(monkeypatch):
    """Install controllable stubs for every upstream product."""

    state = {"cloud_low": 0.0, "kp": 4.0, "fail": set()}

    def kp_forecast():
        if "kp" in state["fail"]:
            raise SourceError("stubbed failure")
        start = at("2026-12-20T00:00")
        return swpc.KpForecast(
            entries=[(start + timedelta(hours=3 * i), state["kp"], i > 2) for i in range(40)],
            fetched_at=start,
        )

    def outlook():
        if "outlook" in state["fail"]:
            raise SourceError("stubbed failure")
        days = {
            (at("2026-12-20T00:00") + timedelta(days=d)).date().isoformat(): state["kp"]
            for d in range(27)
        }
        return swpc.Outlook27Day(
            issued=at("2026-12-18T12:00"), largest_kp=days, fetched_at=at("2026-12-18T12:00")
        )

    def no_op_ovation():
        raise SourceError("stubbed failure")

    def no_op_wind():
        raise SourceError("stubbed failure")

    def alerts():
        return swpc.SpaceWeatherAlerts(messages=[])

    monkeypatch.setattr("aurorafox.watch.swpc.fetch_kp_forecast", kp_forecast)
    monkeypatch.setattr("aurorafox.watch.swpc.fetch_27day_outlook", outlook)
    monkeypatch.setattr("aurorafox.watch.swpc.fetch_ovation", no_op_ovation)
    monkeypatch.setattr("aurorafox.watch.swpc.fetch_solar_wind", no_op_wind)
    monkeypatch.setattr("aurorafox.watch.swpc.fetch_alerts", alerts)
    monkeypatch.setattr(
        "aurorafox.watch.fetch_point",
        lambda point: make_forecast(point, cloud_low=state["cloud_low"])
        if state["cloud_low"] is not None
        else (_ for _ in ()).throw(SourceError("stubbed failure")),
    )
    return state


# ---------------------------------------------------------------------------


def test_perfect_midwinter_conditions_produce_an_alert(stub_sources):
    watch = run_aurora_watch(cities=["tromso"], days=3, now=MIDWINTER)
    assert watch.alerts, "clear polar night at Kp 4 should alert"
    alert = watch.alerts[0]
    assert alert.score >= 7.0
    assert alert.window_hours >= MIN_WINDOW_HOURS
    assert alert.best_cluster is not None
    assert len(alert.best_cluster.members) >= 3
    assert alert.best_cluster.span_km > 10.0


def test_midsummer_produces_nothing_anywhere(stub_sources):
    """The darkness gate must veto the whole summer regardless of everything else."""
    watch = run_aurora_watch(days=5, now=MIDSUMMER)
    assert watch.alerts == []
    for outlook in watch.cities:
        for night in outlook.nights:
            assert night.score == 1.0, (outlook.city.key, night.night)
            assert night.dark_hours == 0


def test_overcast_kills_an_otherwise_perfect_night(stub_sources):
    stub_sources["cloud_low"] = 100.0
    watch = run_aurora_watch(cities=["tromso"], days=3, now=MIDWINTER)
    assert watch.alerts == []
    best = watch.city("tromso").best
    assert best.peak.limiting_factor == "cloud"


def test_quiet_geomagnetic_conditions_kill_a_perfectly_clear_night(stub_sources):
    stub_sources["kp"] = 0.0
    watch = run_aurora_watch(cities=["rovaniemi"], days=3, now=MIDWINTER)
    assert watch.alerts == []
    best = watch.city("rovaniemi").best
    assert best.peak.limiting_factor == "aurora activity"


def test_days_four_and_five_are_capped_and_never_alert(stub_sources):
    watch = run_aurora_watch(cities=["tromso"], days=5, now=MIDWINTER)
    long_range = [
        night
        for night in watch.city("tromso").nights
        if night.peak.lead_hours > 72.0
    ]
    assert long_range, "a 5-day run must contain long-range nights"
    for night in long_range:
        assert night.score <= LONG_RANGE_SCORE_CAP
    assert all(alert.peak.lead_hours <= 72.0 for alert in watch.alerts)


def test_long_range_clear_nights_reach_the_watchlist_instead(stub_sources):
    watch = run_aurora_watch(cities=["tromso"], days=5, now=MIDWINTER)
    assert watch.clear_sky_watchlist, "clear days 4-5 should surface as a watchlist"
    for item in watch.clear_sky_watchlist:
        assert item.lead_days >= 3.0
        assert item.sky >= 0.7
        assert item.anchor


def test_the_same_conditions_score_lower_further_out(stub_sources, monkeypatch):
    """Cloud and Kp are held identical at every hour, so the decline across the
    five days is the horizon-confidence shrink and nothing else.

    The moon is pinned out for this test: it genuinely moves night to night, and
    within the flat 72-120 h tier it would otherwise be the *only* thing varying,
    producing wobble that has nothing to do with the property under test.
    """
    monkeypatch.setattr("aurorafox.scoring.combine.moon_factor", lambda *a: 1.0)
    watch = run_aurora_watch(cities=["tromso"], days=5, now=MIDWINTER)
    nights = [n for n in watch.city("tromso").nights if n.dark_hours > 4 and not n.truncated]
    scores = [n.score for n in nights]
    assert len(scores) >= 4
    assert scores == sorted(scores, reverse=True), scores
    assert scores[0] - scores[-1] > 1.0
    assert scores[-1] < 7.0


def test_a_truncated_final_night_never_alerts(stub_sources):
    watch = run_aurora_watch(cities=["tromso"], days=5, now=MIDWINTER)
    truncated = [n for n in watch.city("tromso").nights if n.truncated]
    for night in truncated:
        assert not night.qualifies
        assert night not in watch.alerts


def test_a_single_good_hour_is_not_a_window(stub_sources, monkeypatch):
    """A lone hour above threshold should not be reported as a window."""
    from aurorafox.watch import _find_window

    class Hour:
        def __init__(self, score, time):
            self.score, self.time = score, time

    base = at("2026-12-21T20:00")
    hours = [Hour(s, base + timedelta(hours=i)) for i, s in enumerate([2, 8, 2, 8, 8, 2])]
    start, end = _find_window(hours, 7.0)
    assert start == base + timedelta(hours=3)
    assert end == base + timedelta(hours=4)


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def test_total_space_weather_failure_degrades_rather_than_crashing(stub_sources):
    stub_sources["fail"] = {"kp", "outlook"}
    watch = run_aurora_watch(cities=["tromso"], days=2, now=MIDWINTER)
    assert watch.alerts == []
    assert any("No geomagnetic forecast" in w for w in watch.warnings)
    assert any(s.status == "unavailable" for s in watch.sources)
    # Scores still render; they are simply floors.
    assert all(n.score >= 1.0 for n in watch.city("tromso").nights)


def test_cloud_forecast_failure_is_reported_per_point(stub_sources):
    stub_sources["cloud_low"] = None  # makes fetch_point raise
    watch = run_aurora_watch(cities=["kiruna"], days=2, now=MIDWINTER)
    outlook = watch.city("kiruna")
    assert outlook.points_used == 0
    assert len(outlook.points_failed) == len(get_city("kiruna").points)
    assert watch.alerts == []
    assert any("no cloud forecast" in w for w in watch.warnings)


def test_missing_cloud_data_does_not_invent_a_clear_sky(stub_sources):
    """With no weather at all, no cluster exists and the score must collapse."""
    stub_sources["cloud_low"] = None
    watch = run_aurora_watch(cities=["kiruna"], days=2, now=MIDWINTER)
    for night in watch.city("kiruna").nights:
        assert night.best_cluster is None
        assert night.score < 4.0


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


def test_all_four_cities_are_scored_by_default(stub_sources):
    watch = run_aurora_watch(days=2, now=MIDWINTER)
    assert {o.city.key for o in watch.cities} == {
        "tromso", "kiruna", "rovaniemi", "reykjavik"
    }
    assert all(o.points_used > 8 for o in watch.cities)


def test_alerts_are_sorted_best_first(stub_sources):
    watch = run_aurora_watch(days=3, now=MIDWINTER)
    scores = [alert.score for alert in watch.alerts]
    assert scores == sorted(scores, reverse=True)


def test_threshold_is_respected(stub_sources):
    strict = run_aurora_watch(cities=["tromso"], days=3, threshold=9.9, now=MIDWINTER)
    loose = run_aurora_watch(cities=["tromso"], days=3, threshold=3.0, now=MIDWINTER)
    assert len(loose.alerts) > len(strict.alerts)


def test_report_renders_without_error(stub_sources):
    from aurorafox.report import render, render_explain

    watch = run_aurora_watch(cities=["tromso"], days=5, now=MIDWINTER)
    text = render(watch)
    assert "AURORA WATCH" in text
    assert "TROMSO" in text
    assert render_explain(watch.city("tromso"))


def test_json_output_is_serialisable(stub_sources):
    import json

    from aurorafox.cli import _to_json

    watch = run_aurora_watch(cities=["tromso"], days=5, now=MIDWINTER)
    payload = json.loads(_to_json(watch))
    assert payload["cities"][0]["key"] == "tromso"
    assert payload["threshold"] == 7.0
    night = payload["cities"][0]["nights"][0]
    for key in ("aurora_potential", "sky", "darkness", "moon_factor", "limiting_factor"):
        assert key in night
