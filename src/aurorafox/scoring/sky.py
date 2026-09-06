"""Cloud scoring, and the spatial-coherence rule that governs it.

Two ideas, and the second is the one that keeps this honest.

**1. Vertical structure beats total cover.** For aurora, *which* cloud is in the
way matters more than how much. Thin cirrus at 8 km dims a display; a low
stratus deck ends it. So the layers are weighted separately rather than reading
``cloud_area_fraction``.

**2. A single clear grid point is not a clear sky.** Forecast models put cloud
bands in roughly the right place, not exactly the right place. A lone clear
point surrounded by cloud is far more likely to be a positioning error than a
real hole you can drive to. So no location scores on its own: a point is only
eligible if it anchors a *cluster* of nearby points, and the cluster is scored
at a low percentile of its members. In plain terms the question asked is not
"is it clear here?" but "is most of the area within 40 km clear?".
"""

from __future__ import annotations

from dataclasses import dataclass

from ..geo import clamp, haversine_km, percentile
from ..locations import ViewingPoint
from ..sources.metno import PointForecast, WeatherSample

# Layer penalties. Starting heuristic from the design note, not a calibrated
# radiative-transfer model - the relative ordering is what carries the weight.
LOW_CLOUD_PENALTY = 0.55
MEDIUM_CLOUD_PENALTY = 0.30
HIGH_CLOUD_PENALTY = 0.15

# Region size. 40 km is the scale at which a "clear window" is worth driving to
# and large enough that a mislocated cloud edge does not fake one.
CLUSTER_RADIUS_KM = 40.0
MIN_CLUSTER_MEMBERS = 3

# Conservative aggregation: the value below which 30% of the cluster's points
# fall. Reads as "at least ~70% of the sampled area is at least this clear."
CLUSTER_PERCENTILE = 30.0

# A point is "clear" for footprint-reporting purposes at this sky score.
CLEAR_THRESHOLD = 0.70

# Long-range samples lose fog_area_fraction entirely. Humidity is a weak proxy;
# this is the strongest penalty it may impose, well below what real fog costs.
MAX_HUMIDITY_PROXY_PENALTY = 0.25


@dataclass(frozen=True, slots=True)
class PointSky:
    """One point's clarity at one hour."""

    point: ViewingPoint
    sky: float
    cloud_low: float | None
    cloud_medium: float | None
    cloud_high: float | None
    fog: float | None
    fog_estimated: bool
    precipitation_mm: float | None
    interpolated: bool


@dataclass(frozen=True, slots=True)
class ClusterSky:
    """A region's clarity: an anchor plus the neighbours that back it up."""

    anchor: ViewingPoint
    members: tuple[PointSky, ...]
    sky: float
    span_km: float

    @property
    def member_names(self) -> tuple[str, ...]:
        return tuple(m.point.name for m in self.members)

    @property
    def clear_members(self) -> tuple[str, ...]:
        return tuple(m.point.name for m in self.members if m.sky >= CLEAR_THRESHOLD)


def precipitation_penalty(mm_per_hour: float | None) -> float:
    """Falling precipitation means cloud overhead, whatever the layers say."""
    if not mm_per_hour:
        return 1.0
    # 0.5 mm/h already implies a solid deck.
    return clamp(1.0 - min(1.0, mm_per_hour / 0.5), 0.0, 1.0)


def point_sky_score(sample: WeatherSample) -> tuple[float, bool]:
    """Clarity in 0..1 for one sample. Returns (score, fog_was_estimated).

    Missing fields degrade the score's *confidence*, never silently read as
    zero cloud: at long range MET stops sending ``fog_area_fraction`` entirely,
    and treating that absence as "no fog" would systematically flatter days 4-5.
    """
    low = sample.cloud_low
    medium = sample.cloud_medium
    high = sample.cloud_high

    if low is None and medium is None and high is None:
        # Fall back to total cover, penalised as if it were mid-level.
        if sample.cloud_total is None:
            return 0.0, False
        score = 1.0 - 0.45 * sample.cloud_total / 100.0
    else:
        score = 1.0
        score -= LOW_CLOUD_PENALTY * (low or 0.0) / 100.0
        score -= MEDIUM_CLOUD_PENALTY * (medium or 0.0) / 100.0
        score -= HIGH_CLOUD_PENALTY * (high or 0.0) / 100.0

    fog_estimated = False
    if sample.fog is not None:
        score *= 1.0 - sample.fog / 100.0
    elif sample.relative_humidity is not None:
        # Above ~92% RH with low cloud present, fog or very low stratus becomes
        # plausible. Deliberately capped: this is a hint, not a measurement.
        fog_estimated = True
        excess = max(0.0, sample.relative_humidity - 92.0) / 8.0
        low_cloud_support = clamp((low or 0.0) / 60.0)
        score *= 1.0 - MAX_HUMIDITY_PROXY_PENALTY * clamp(excess) * low_cloud_support

    score *= precipitation_penalty(sample.precipitation_mm)
    return clamp(score), fog_estimated


def score_points(
    forecasts: dict[str, PointForecast], when
) -> list[PointSky]:
    """Score every point that has data for this hour."""
    out: list[PointSky] = []
    for forecast in forecasts.values():
        sample = forecast.at(when)
        if sample is None:
            continue
        score, fog_estimated = point_sky_score(sample)
        out.append(
            PointSky(
                point=forecast.point,
                sky=score,
                cloud_low=sample.cloud_low,
                cloud_medium=sample.cloud_medium,
                cloud_high=sample.cloud_high,
                fog=sample.fog,
                fog_estimated=fog_estimated,
                precipitation_mm=sample.precipitation_mm,
                interpolated=sample.interpolated,
            )
        )
    return out


def best_cluster(points: list[PointSky]) -> ClusterSky | None:
    """The clearest region that satisfies the coherence rule.

    Every point is tried as an anchor. An anchor whose neighbourhood holds fewer
    than :data:`MIN_CLUSTER_MEMBERS` sampled points is **not eligible at all**,
    however clear it looks on its own - that is exactly the isolated-clear-pixel
    case this rule exists to reject.
    """
    best: ClusterSky | None = None
    for anchor in points:
        members = [
            other
            for other in points
            if haversine_km(
                anchor.point.lat, anchor.point.lon, other.point.lat, other.point.lon
            )
            <= CLUSTER_RADIUS_KM
        ]
        if len(members) < MIN_CLUSTER_MEMBERS:
            continue
        score = percentile([m.sky for m in members], CLUSTER_PERCENTILE)
        span = max(
            (
                haversine_km(a.point.lat, a.point.lon, b.point.lat, b.point.lon)
                for a in members
                for b in members
            ),
            default=0.0,
        )
        candidate = ClusterSky(
            anchor=anchor.point,
            members=tuple(sorted(members, key=lambda m: -m.sky)),
            sky=score,
            span_km=span,
        )
        if best is None or candidate.sky > best.sky:
            best = candidate
    return best


def clear_footprint(points: list[PointSky]) -> tuple[int, float]:
    """Diagnostic: how many points are clear, and how far apart they spread."""
    clear = [p for p in points if p.sky >= CLEAR_THRESHOLD]
    if len(clear) < 2:
        return len(clear), 0.0
    span = max(
        haversine_km(a.point.lat, a.point.lon, b.point.lat, b.point.lon)
        for a in clear
        for b in clear
    )
    return len(clear), span
