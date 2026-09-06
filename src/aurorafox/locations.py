"""Curated, road-accessible viewing sites for the four tracked cities.

Each city carries a set of real places you can drive to, spread widely enough
that the cloud-clustering in :mod:`aurorafox.scoring.sky` can ask whether a
*region* is clear rather than a single model grid point.

Two per-city constants deserve explanation:

``cgm_latitude``
    Corrected geomagnetic latitude (AACGM-v2, epoch ~2025), rounded to 0.1 deg.
    The auroral oval is organised by geomagnetic, not geographic, latitude, and
    at these sites the two differ by 2-6 degrees in different directions.
    Reykjavik is the case that makes the point: its geographic latitude is a
    full 2.4 deg *south* of Rovaniemi's, yet its geomagnetic latitude is about
    1 deg *north* of it, because the geomagnetic pole sits over Arctic Canada.
    A model keyed on geographic latitude ranks those two backwards.

``magnetic_midnight_utc``
    Hour (UTC, fractional) at which the site passes through the midnight sector
    of the oval, where auroral activity concentrates. Derived from the site's
    geomagnetic longitude; accurate to roughly +/- 20 minutes, which is well
    inside the resolution of anything else in this model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geo import haversine_km


@dataclass(frozen=True, slots=True)
class ViewingPoint:
    """A specific place you can drive to and stand in."""

    name: str
    lat: float
    lon: float
    altitude_m: int
    road_note: str
    drive_minutes: int


@dataclass(frozen=True, slots=True)
class City:
    """A tracked destination and its surrounding viewing points."""

    key: str
    name: str
    country: str
    lat: float
    lon: float
    timezone: str
    cgm_latitude: float
    magnetic_midnight_utc: float
    radius_note: str
    points: tuple[ViewingPoint, ...]

    def distance_km(self, point: ViewingPoint) -> float:
        return haversine_km(self.lat, self.lon, point.lat, point.lon)

    @property
    def max_point_distance_km(self) -> float:
        return max(self.distance_km(p) for p in self.points)


TROMSO = City(
    key="tromso",
    name="Tromso",
    country="Norway",
    lat=69.6492,
    lon=18.9553,
    timezone="Europe/Oslo",
    cgm_latitude=66.6,
    magnetic_midnight_utc=21.5,
    radius_note="Expanded to ~140 km: the E6/E8 corridor inland is the standard "
    "escape from coastal cloud and is reachable in an evening.",
    points=(
        ViewingPoint("Tromso", 69.6492, 18.9553, 10, "City centre, E8", 0),
        ViewingPoint("Kvaloysletta", 69.6906, 18.8353, 20, "Fv862 over Sandnessundet bridge", 15),
        ViewingPoint("Ersfjordbotn", 69.6683, 18.5525, 5, "Fv862, head of Ersfjord", 30),
        ViewingPoint("Tromvik", 69.8697, 18.3300, 5, "Fv863, north-west Kvaloya", 70),
        ViewingPoint("Sommaroy", 69.6383, 18.0083, 5, "Fv862 to the western islands", 65),
        ViewingPoint("Breivikeidet", 69.5478, 19.5203, 20, "Fv91, inland valley", 45),
        ViewingPoint("Nordkjosbotn", 69.2183, 19.5442, 10, "E6/E8 junction, inland", 60),
        ViewingPoint("Oteren", 69.2450, 19.9583, 10, "E8 towards Finland", 75),
        ViewingPoint("Skibotn", 69.3906, 20.2683, 5, "E8, driest microclimate in the region", 90),
        ViewingPoint("Mestervik", 69.3167, 18.7500, 10, "Fv858 around Malangen", 55),
        ViewingPoint("Bardufoss", 69.0667, 18.5333, 75, "E6 south, continental inland", 100),
        ViewingPoint("Olsborg", 69.0442, 18.9139, 60, "E6, Malselv valley", 105),
        ViewingPoint("Finnsnes", 69.2294, 17.9817, 10, "E6 then Fv86, Senja gateway", 110),
        ViewingPoint("Rotsundelv", 69.6403, 20.7092, 10, "E6 north-east", 125),
        ViewingPoint("Storslett", 69.7667, 21.0333, 10, "E6 north-east, Reisadalen", 140),
        ViewingPoint("Skjervoy", 70.0311, 20.9711, 10, "Fv866 off the E6", 160),
    ),
)

KIRUNA = City(
    key="kiruna",
    name="Kiruna",
    country="Sweden",
    lat=67.8558,
    lon=20.2253,
    timezone="Europe/Stockholm",
    cgm_latitude=64.8,
    magnetic_midnight_utc=21.7,
    radius_note="~120 km along the E10 west to Abisko and the E45 south to Gallivare.",
    points=(
        ViewingPoint("Kiruna", 67.8558, 20.2253, 500, "Town centre, E10", 0),
        ViewingPoint("Jukkasjarvi", 67.8497, 20.6608, 340, "Rd 870 east along the Torne river", 20),
        ViewingPoint("Kurravaara", 67.9167, 20.3833, 420, "Minor road north of Kiruna", 20),
        ViewingPoint("Rensjon", 67.9847, 19.6528, 500, "E10 west of Kiruna", 35),
        ViewingPoint("Nikkaluokta", 67.8500, 19.0167, 470, "Rd 870 west, end of the road", 60),
        ViewingPoint("Fjallasen", 67.4667, 20.5000, 480, "Rd 395 south, inland forest", 60),
        ViewingPoint("Svappavaara", 67.6486, 21.0272, 400, "E10/E45 junction", 45),
        ViewingPoint("Merasjarvi", 67.5333, 21.6000, 340, "Rd 395 south of Vittangi", 70),
        ViewingPoint("Vittangi", 67.6803, 21.6350, 300, "E45 east, continental", 60),
        ViewingPoint("Tornetrask", 68.2244, 19.7264, 350, "E10 west, lake shore", 65),
        ViewingPoint("Kaisepakte", 68.2833, 19.4167, 400, "E10, between Tornetrask and Abisko", 70),
        ViewingPoint("Abisko", 68.3494, 18.8306, 400, "E10, the Lapporten rain shadow", 85),
        ViewingPoint("Bjorkliden", 68.4092, 18.6994, 500, "E10, furthest west before the border", 95),
        ViewingPoint("Puoltikasvaara", 67.4022, 21.0139, 350, "E45 south", 75),
        ViewingPoint("Gallivare", 67.1355, 20.6600, 360, "E45 south, ~120 km", 100),
    ),
)

ROVANIEMI = City(
    key="rovaniemi",
    name="Rovaniemi",
    country="Finland",
    lat=66.5039,
    lon=25.7294,
    timezone="Europe/Helsinki",
    cgm_latitude=63.3,
    magnetic_midnight_utc=21.0,
    radius_note="~100 km along the E75, Rd 79, Rd 81 and Rd 78; the flattest, most uniform "
    "terrain of the four, so cloud fields vary less across the set.",
    points=(
        ViewingPoint("Rovaniemi", 66.5039, 25.7294, 85, "City centre, E75", 0),
        ViewingPoint("Muurola", 66.4167, 25.3000, 90, "Rd 926 south-west", 20),
        ViewingPoint("Sinetta", 66.6167, 25.1833, 100, "Rd 79 north-west", 30),
        ViewingPoint("Vikajarvi", 66.6153, 26.1858, 130, "E63/Rd 82 junction", 30),
        ViewingPoint("Narkaus", 66.2833, 26.1500, 140, "Rd 81 south-east", 40),
        ViewingPoint("Marraskoski", 66.7167, 25.3167, 105, "Rd 79 north", 45),
        ViewingPoint("Meltaus", 66.8667, 25.3667, 110, "Rd 79 north", 55),
        ViewingPoint("Vanttauskoski", 66.4667, 26.6500, 120, "Rd 81 east", 45),
        ViewingPoint("Auttikongas", 66.4667, 27.0333, 150, "Rd 81 east", 60),
        ViewingPoint("Kemijarvi", 66.7139, 27.4278, 150, "E63 north-east", 75),
        ViewingPoint("Petajaskoski", 66.2667, 25.1167, 80, "Rd 926 south-west", 40),
        ViewingPoint("Koivu", 66.1833, 24.9667, 70, "Rd 926 / E75 south-west", 50),
        ViewingPoint("Tervola", 66.0806, 24.8083, 60, "E75 south-west", 60),
        ViewingPoint("Saukkojarvi", 66.0833, 26.4000, 150, "Rd 78 south", 55),
        ViewingPoint("Ranua", 65.9297, 26.5175, 165, "Rd 78 south", 70),
    ),
)

REYKJAVIK = City(
    key="reykjavik",
    name="Reykjavik",
    country="Iceland",
    lat=64.1466,
    lon=-21.9426,
    timezone="Atlantic/Reykjavik",
    cgm_latitude=64.3,
    magnetic_midnight_utc=23.5,
    radius_note="~110 km on Rd 1, 36, 41 and 42. Maritime and fast-changing: the "
    "spread between the peninsula and the interior is often the whole story.",
    points=(
        ViewingPoint("Reykjavik", 64.1466, -21.9426, 15, "City centre", 0),
        ViewingPoint("Kleifarvatn", 63.9333, -22.0333, 140, "Rd 42, Reykjanes interior", 40),
        ViewingPoint("Grindavik", 63.8353, -22.4269, 15, "Rd 43, south-west coast", 50),
        ViewingPoint("Gardur", 64.0806, -22.6889, 5, "Rd 45, north-west tip of Reykjanes", 50),
        ViewingPoint("Hveragerdi", 64.0000, -21.1861, 60, "Rd 1 east over Hellisheidi", 40),
        ViewingPoint("Thingvellir", 64.2559, -21.1300, 110, "Rd 36, rift valley", 50),
        ViewingPoint("Akranes", 64.3222, -22.0750, 10, "Rd 1 through Hvalfjordur tunnel", 45),
        ViewingPoint("Hvalfjordur", 64.3833, -21.4667, 20, "Rd 47 around the fjord", 60),
        ViewingPoint("Selfoss", 63.9333, -21.0000, 15, "Rd 1 east", 50),
        ViewingPoint("Eyrarbakki", 63.8639, -21.1528, 5, "Rd 34, south coast", 60),
        ViewingPoint("Laugarvatn", 64.2167, -20.7333, 100, "Rd 37, inland", 75),
        ViewingPoint("Borgarnes", 64.5383, -21.9219, 10, "Rd 1 north", 70),
        ViewingPoint("Reykholt", 64.6667, -21.2833, 90, "Rd 50/518, Borgarfjordur interior", 90),
        ViewingPoint("Hella", 63.8333, -20.4000, 25, "Rd 1 east", 75),
        ViewingPoint("Hvolsvollur", 63.7500, -20.2333, 40, "Rd 1 east, ~105 km", 85),
    ),
)

CITIES: dict[str, City] = {c.key: c for c in (TROMSO, KIRUNA, ROVANIEMI, REYKJAVIK)}


def get_city(key: str) -> City:
    """Look up a city by key, case- and accent-insensitively where obvious."""
    normalised = key.strip().lower().replace("ø", "o").replace("í", "i").replace("å", "a")
    if normalised in CITIES:
        return CITIES[normalised]
    raise KeyError(f"unknown city {key!r}; known: {', '.join(sorted(CITIES))}")


def all_cities() -> tuple[City, ...]:
    return (TROMSO, KIRUNA, ROVANIEMI, REYKJAVIK)
