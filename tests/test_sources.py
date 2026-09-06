"""Parsers, exercised against recorded real responses. No network."""

from __future__ import annotations

from itertools import pairwise
from datetime import datetime, timedelta, timezone

import pytest

from aurorafox.locations import get_city
from aurorafox.sources import swpc
from aurorafox.sources.http import Response, SourceError, _expiry_from_headers, user_agent
from aurorafox.sources.metno import parse
from conftest import load_json, load_text

TROMSO = get_city("tromso")


def fake_response(url: str = "https://example.invalid") -> Response:
    return Response(url=url, text="", fetched_at=datetime.now(timezone.utc), from_cache=False)


# ---------------------------------------------------------------------------
# MET Norway
# ---------------------------------------------------------------------------


def test_metno_parses_recorded_response():
    forecast = parse(load_json("metno_tromso.json"), TROMSO.points[0], fake_response())
    assert forecast.updated_at is not None
    assert len(forecast.samples) > 12
    first = min(forecast.samples)
    sample = forecast.samples[first]
    assert sample.cloud_low is not None
    assert sample.interpolated is False


def test_metno_resamples_the_six_hourly_tail_onto_hourly_steps():
    """The native series switches resolution partway through; the grid must not."""
    forecast = parse(load_json("metno_tromso.json"), TROMSO.points[0], fake_response())
    times = sorted(forecast.samples)
    gaps = {
        int((b - a).total_seconds() // 3600)
        for a, b in pairwise(times)
        # The fixture is deliberately non-contiguous, so ignore the deleted spans.
        if (b - a) <= timedelta(hours=6)
    }
    assert gaps == {1}


def test_metno_flags_interpolated_samples():
    forecast = parse(load_json("metno_tromso.json"), TROMSO.points[0], fake_response())
    interpolated = [s for s in forecast.samples.values() if s.interpolated]
    assert interpolated, "fixture should span the hourly/6-hourly boundary"
    assert all(s.native_step_hours > 1.0 for s in interpolated)


def test_metno_preserves_missing_fog_at_long_range():
    """The field genuinely disappears; it must arrive as None, never as 0.0."""
    forecast = parse(load_json("metno_tromso.json"), TROMSO.points[0], fake_response())
    ordered = [forecast.samples[t] for t in sorted(forecast.samples)]
    assert ordered[0].fog is not None
    assert any(s.fog is None for s in ordered), "fixture should include a fog-less sample"
    assert not any(s.fog == 0.0 and not s.has_fog_field for s in ordered)


def test_metno_rejects_a_malformed_payload():
    with pytest.raises(SourceError):
        parse({"properties": {}}, TROMSO.points[0], fake_response())
    with pytest.raises(SourceError):
        parse({"properties": {"timeseries": []}}, TROMSO.points[0], fake_response())


def test_metno_normalises_six_hourly_precipitation_to_per_hour():
    forecast = parse(load_json("metno_tromso.json"), TROMSO.points[0], fake_response())
    for sample in forecast.samples.values():
        if sample.precipitation_mm is not None:
            assert 0.0 <= sample.precipitation_mm < 30.0


# ---------------------------------------------------------------------------
# SWPC
# ---------------------------------------------------------------------------


def test_kp_forecast_parses_and_separates_observed_from_predicted(monkeypatch):
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_kp_forecast.json"))
    forecast = swpc.fetch_kp_forecast()
    assert len(forecast.entries) > 50
    assert any(predicted for _, _, predicted in forecast.entries)
    assert any(not predicted for _, _, predicted in forecast.entries)
    assert forecast.entries == sorted(forecast.entries)


def test_kp_forecast_horizon_stops_around_three_days(monkeypatch):
    """The constraint the whole horizon-tier design is built around."""
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_kp_forecast.json"))
    forecast = swpc.fetch_kp_forecast()
    first = min(t for t, _, _ in forecast.entries)
    span_hours = (forecast.horizon_end - first).total_seconds() / 3600.0
    assert span_hours < 11 * 24, "product should not claim a long-range forecast"


def test_kp_lookup_uses_three_hour_bins(monkeypatch):
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_kp_forecast.json"))
    forecast = swpc.fetch_kp_forecast()
    bin_start, kp, _ = forecast.entries[10]
    assert forecast.at(bin_start) == kp
    assert forecast.at(bin_start + timedelta(hours=2, minutes=59)) == kp
    assert forecast.at(bin_start + timedelta(days=40)) is None


def test_ovation_interpolates_and_normalises_longitude(monkeypatch):
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_ovation.json"))
    nowcast = swpc.fetch_ovation()
    tromso = nowcast.probability(TROMSO.lat, TROMSO.lon)
    assert tromso is not None and 0.0 <= tromso <= 100.0
    # Reykjavik sits at negative longitude; the grid is 0..359.
    reykjavik = get_city("reykjavik")
    assert nowcast.probability(reykjavik.lat, reykjavik.lon) is not None
    # Outside the trimmed fixture window there is simply no data.
    assert nowcast.probability(0.0, 100.0) is None


def test_ovation_validity_window_is_short(monkeypatch):
    """It is a nowcast, and must not be treated as a forecast."""
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_ovation.json"))
    nowcast = swpc.fetch_ovation()
    assert nowcast.is_valid_for(nowcast.forecast_time)
    assert not nowcast.is_valid_for(nowcast.forecast_time + timedelta(hours=8))


def test_solar_wind_parses_header_row_format(monkeypatch):
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_solar_wind.json"))
    wind = swpc.fetch_solar_wind()
    assert wind.bz is not None
    assert wind.speed is not None and wind.speed > 100
    assert wind.mean_bz_30min is not None


def test_solar_wind_boost_responds_to_southward_bz():
    quiet = swpc.SolarWind(datetime.now(timezone.utc), 1.0, 5.0, 380.0, 5.0, 1.0)
    storm = swpc.SolarWind(datetime.now(timezone.utc), -14.0, 18.0, 650.0, 12.0, -12.0)
    assert swpc.solar_wind_boost(quiet) == 0.0
    assert swpc.solar_wind_boost(storm) > 0.7
    assert not quiet.is_southward
    assert storm.is_southward


def test_27day_outlook_parses_issue_date_and_daily_kp(monkeypatch):
    monkeypatch.setattr(
        swpc, "fetch", lambda *a, **k: Response(
            url="x", text=load_text("swpc_27day.txt"),
            fetched_at=datetime.now(timezone.utc), from_cache=False,
        )
    )
    outlook = swpc.fetch_27day_outlook()
    assert outlook.issued is not None
    assert len(outlook.largest_kp) == 27
    assert all(0.0 <= kp <= 9.0 for kp in outlook.largest_kp.values())
    age = outlook.age_days(outlook.issued + timedelta(days=4))
    assert age == pytest.approx(4.0)


def test_alerts_extract_geomagnetic_headlines(monkeypatch):
    monkeypatch.setattr(swpc, "fetch", lambda *a, **k: _json_response("swpc_alerts.json"))
    alerts = swpc.fetch_alerts()
    assert alerts.messages
    newest = alerts.messages[0][0]
    level = alerts.max_watch_level(newest)
    assert 0 <= level <= 5
    # Nothing from long ago should count as active.
    assert alerts.active_geomagnetic(newest + timedelta(days=30)) == []


def _json_response(name: str) -> Response:
    import json

    return Response(
        url="x",
        text=json.dumps(load_json(name)),
        fetched_at=datetime.now(timezone.utc),
        from_cache=False,
    )


# ---------------------------------------------------------------------------
# HTTP policy
# ---------------------------------------------------------------------------


def test_user_agent_identifies_the_app_and_is_overridable(monkeypatch):
    """MET Norway's terms require this; a generic agent gets a 403."""
    assert "aurorafox" in user_agent()
    monkeypatch.setenv("AURORAFOX_USER_AGENT", "myapp/1.0 me@example.com")
    assert user_agent() == "myapp/1.0 me@example.com"


def test_expiry_prefers_the_server_header_within_sane_bounds():
    """MET sends Expires and asks clients to respect it, so it wins - but only
    inside bounds, so neither a stale nor an absurdly distant header can pin the
    cache."""
    from email.utils import formatdate

    now = datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc).timestamp()

    def expires_in(seconds: float) -> dict[str, str]:
        return {"Expires": formatdate(now + seconds, usegmt=True)}

    # A normal MET header ~30 minutes out is used as-is.
    assert _expiry_from_headers(expires_in(1800), now, 300.0) == pytest.approx(
        now + 1800, abs=1.0
    )
    # An already-expired header is floored at 60 s rather than causing a refetch storm.
    assert _expiry_from_headers(expires_in(-5000), now, 300.0) == pytest.approx(now + 60.0)
    # An implausibly distant header is capped at 6 hours.
    assert _expiry_from_headers(expires_in(10 * 86400), now, 300.0) == pytest.approx(
        now + 6 * 3600.0
    )
    # No header at all: the caller's TTL applies.
    assert _expiry_from_headers({}, now, 300.0) == now + 300.0
    # An unparseable header falls back rather than raising.
    assert _expiry_from_headers({"Expires": "nonsense"}, now, 300.0) == now + 300.0
