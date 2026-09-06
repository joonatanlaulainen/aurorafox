"""The curated viewing points have to satisfy the clustering rule to be useful."""

from __future__ import annotations

import pytest

from aurorafox.geo import haversine_km
from aurorafox.locations import CITIES, all_cities, get_city
from aurorafox.scoring.sky import CLUSTER_RADIUS_KM, MIN_CLUSTER_MEMBERS


@pytest.mark.parametrize("city", all_cities(), ids=lambda c: c.key)
def test_every_point_is_within_reach(city):
    """Everything must be a plausible evening drive."""
    limit = 150.0 if city.key == "tromso" else 125.0
    for point in city.points:
        assert city.distance_km(point) <= limit, point.name


@pytest.mark.parametrize("city", all_cities(), ids=lambda c: c.key)
def test_points_are_distinct(city):
    names = [p.name for p in city.points]
    assert len(names) == len(set(names))
    for i, a in enumerate(city.points):
        for b in city.points[i + 1 :]:
            # Two points closer than 5 km sample the same weather twice.
            assert haversine_km(a.lat, a.lon, b.lat, b.lon) > 5.0, f"{a.name}/{b.name}"


@pytest.mark.parametrize("city", all_cities(), ids=lambda c: c.key)
def test_enough_anchors_can_form_clusters(city):
    """At least half the points must be able to anchor an eligible cluster.

    If they cannot, the coherence rule would silently discard most of the city's
    coverage and the scores would come from a handful of places.
    """
    eligible = 0
    for anchor in city.points:
        neighbours = sum(
            1
            for other in city.points
            if haversine_km(anchor.lat, anchor.lon, other.lat, other.lon)
            <= CLUSTER_RADIUS_KM
        )
        if neighbours >= MIN_CLUSTER_MEMBERS:
            eligible += 1
    assert eligible >= len(city.points) / 2, f"{city.key}: only {eligible} anchors"


@pytest.mark.parametrize("city", all_cities(), ids=lambda c: c.key)
def test_points_spread_beyond_one_cluster(city):
    """The set must cover more than a single 40 km blob, or there is no choice."""
    assert city.max_point_distance_km > CLUSTER_RADIUS_KM


def test_geomagnetic_ordering_is_not_geographic():
    """Reykjavik outranks Rovaniemi geomagnetically despite being further south.

    This is the property that makes cgm_latitude worth carrying at all - if it
    ever silently became geographic latitude, this test fails.
    """
    reykjavik, rovaniemi = get_city("reykjavik"), get_city("rovaniemi")
    assert reykjavik.lat < rovaniemi.lat
    assert reykjavik.cgm_latitude > rovaniemi.cgm_latitude


def test_lookup_accepts_accented_spelling():
    assert get_city("Tromsø").key == "tromso"
    assert get_city("TROMSO").key == "tromso"
    with pytest.raises(KeyError):
        get_city("oslo")


def test_all_cities_registered():
    assert set(CITIES) == {"tromso", "kiruna", "rovaniemi", "reykjavik"}
