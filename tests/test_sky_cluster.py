"""Cloud scoring, and the spatial-coherence rule that is the point of it."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aurorafox.locations import ViewingPoint
from aurorafox.scoring.sky import (
    CLEAR_THRESHOLD,
    CLUSTER_RADIUS_KM,
    MIN_CLUSTER_MEMBERS,
    PointSky,
    best_cluster,
    clear_footprint,
    point_sky_score,
    precipitation_penalty,
)
from aurorafox.sources.metno import WeatherSample

NOW = datetime(2026, 12, 21, 22, 0, tzinfo=timezone.utc)


def sample(**overrides) -> WeatherSample:
    base = dict(
        time=NOW,
        cloud_total=None,
        cloud_low=0.0,
        cloud_medium=0.0,
        cloud_high=0.0,
        fog=0.0,
        relative_humidity=70.0,
        precipitation_mm=0.0,
        native_step_hours=1.0,
    )
    base.update(overrides)
    return WeatherSample(**base)


# ---------------------------------------------------------------------------
# Per-point scoring
# ---------------------------------------------------------------------------


def test_layers_are_penalised_in_the_right_order():
    """Same amount of cloud, very different consequences for aurora."""
    low = point_sky_score(sample(cloud_low=80))[0]
    medium = point_sky_score(sample(cloud_medium=80))[0]
    high = point_sky_score(sample(cloud_high=80))[0]
    assert low < medium < high < 1.0


def test_clear_sky_scores_one():
    assert point_sky_score(sample())[0] == pytest.approx(1.0)


def test_fog_is_close_to_disqualifying():
    assert point_sky_score(sample(fog=90))[0] < 0.15


def test_precipitation_zeroes_the_score():
    assert precipitation_penalty(0.0) == 1.0
    assert precipitation_penalty(None) == 1.0
    assert precipitation_penalty(0.6) == 0.0
    assert point_sky_score(sample(cloud_low=20, precipitation_mm=1.0))[0] == 0.0


def test_missing_fog_is_flagged_and_proxied_not_assumed_zero():
    """At long range MET stops sending fog; treating that as 'no fog' would
    systematically flatter days 4-5, which is exactly the wrong direction."""
    score, estimated = point_sky_score(
        sample(fog=None, relative_humidity=99.0, cloud_low=80.0)
    )
    assert estimated is True
    assert score < point_sky_score(sample(fog=None, relative_humidity=60.0, cloud_low=80.0))[0]


def test_humidity_proxy_stays_modest():
    """The proxy is a hint. It must never behave like a measured fog field."""
    proxied = point_sky_score(sample(fog=None, relative_humidity=100.0, cloud_low=100.0))[0]
    measured = point_sky_score(sample(fog=95.0, cloud_low=100.0))[0]
    assert proxied > measured


def test_falls_back_to_total_cover_when_layers_are_absent():
    score, _ = point_sky_score(
        sample(cloud_low=None, cloud_medium=None, cloud_high=None, cloud_total=100.0)
    )
    assert 0.0 < score < 0.6


# ---------------------------------------------------------------------------
# The coherence rule
# ---------------------------------------------------------------------------


def make(name: str, lat: float, lon: float, sky: float) -> PointSky:
    return PointSky(
        point=ViewingPoint(name, lat, lon, 0, "test", 0),
        sky=sky,
        cloud_low=None,
        cloud_medium=None,
        cloud_high=None,
        fog=None,
        fog_estimated=False,
        precipitation_mm=None,
        interpolated=False,
    )


def test_isolated_clear_point_cannot_score():
    """The rule this whole module exists for.

    A single pristine point 200 km from anything else is far more likely to be a
    mislocated cloud edge than a real hole worth driving to, so it must not be
    eligible to anchor a cluster at all.
    """
    points = [
        make("far-away gem", 60.0, 10.0, 1.0),
        make("murk a", 69.0, 20.0, 0.05),
        make("murk b", 69.1, 20.1, 0.05),
        make("murk c", 69.2, 20.2, 0.05),
    ]
    cluster = best_cluster(points)
    assert cluster is not None
    assert cluster.anchor.name != "far-away gem"
    assert cluster.sky < 0.2


def test_no_cluster_when_too_few_points_anywhere():
    points = [make("a", 69.0, 20.0, 1.0), make("b", 69.05, 20.05, 1.0)]
    assert best_cluster(points) is None


def test_one_bad_point_does_not_veto_a_genuinely_clear_region():
    """Deliberately not `min`: a single cloudy fjord should not kill the region."""
    points = [
        make("a", 69.00, 20.00, 0.95),
        make("b", 69.10, 20.10, 0.92),
        make("c", 69.20, 20.20, 0.90),
        make("d", 69.05, 20.30, 0.93),
        make("bad fjord", 69.15, 20.05, 0.10),
    ]
    cluster = best_cluster(points)
    assert cluster is not None
    assert cluster.sky > 0.6


def test_a_mostly_cloudy_region_is_scored_low_despite_a_clear_member():
    """The 30th percentile is what makes 'most of the area' the actual claim."""
    points = [
        make("clear one", 69.00, 20.00, 1.0),
        make("b", 69.05, 20.05, 0.1),
        make("c", 69.10, 20.10, 0.1),
        make("d", 69.15, 20.15, 0.1),
    ]
    cluster = best_cluster(points)
    assert cluster is not None
    assert cluster.sky < 0.3


def test_cluster_members_are_all_within_the_radius():
    from aurorafox.geo import haversine_km

    points = [make(f"p{i}", 69.0 + i * 0.15, 20.0 + i * 0.2, 0.9) for i in range(8)]
    cluster = best_cluster(points)
    assert cluster is not None
    assert len(cluster.members) >= MIN_CLUSTER_MEMBERS
    for member in cluster.members:
        assert (
            haversine_km(
                cluster.anchor.lat, cluster.anchor.lon, member.point.lat, member.point.lon
            )
            <= CLUSTER_RADIUS_KM + 1e-9
        )


def test_clear_footprint_reports_extent_not_just_count():
    points = [
        make("a", 69.0, 20.0, 0.9),
        make("b", 69.5, 21.0, 0.9),
        make("c", 69.2, 20.4, 0.2),
    ]
    count, span = clear_footprint(points)
    assert count == 2
    assert span > 50.0


def test_clear_footprint_of_a_single_point_has_no_span():
    assert clear_footprint([make("a", 69.0, 20.0, 0.9)]) == (1, 0.0)
    assert clear_footprint([make("a", 69.0, 20.0, 0.1)]) == (0, 0.0)


def test_clear_threshold_is_a_meaningful_bar():
    assert 0.5 < CLEAR_THRESHOLD < 0.9
