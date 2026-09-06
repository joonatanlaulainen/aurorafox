"""``run_aurora_watch()`` - the entry point.

Pulls live space weather and cloud forecasts, scores every dark hour at every
tracked city over the next five days, and reports the nights worth acting on.

Failure policy: a source that cannot be read degrades the run and is recorded in
``warnings``; it never aborts it. If MET fails for one viewing point, that point
drops out of its clusters (and may make an anchor ineligible, which is the
correct conservative response). If SWPC's Kp forecast fails entirely, aurora
potential is unavailable and every score collapses - which is reported plainly
rather than papered over with a default.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Sequence

from .astronomy import sky_geometry
from .locations import City, all_cities, get_city
from .scoring.aurora import aurora_potential
from .scoring.combine import (
    LONG_RANGE_HOURS,
    HourScore,
    night_key,
    score_hour,
)
from .scoring.sky import (
    ClusterSky,
    best_cluster,
    clear_footprint,
    score_points,
)
from .sources import swpc
from .sources.http import SourceError
from .sources.metno import PointForecast, fetch_point
from .version import __version__

DEFAULT_DAYS = 5
DEFAULT_THRESHOLD = 7.0
MET_CONCURRENCY = 4

# A single flukey hour above threshold is not a window worth driving for.
MIN_WINDOW_HOURS = 2

# For the days 4-5 watchlist, which is about cloud rather than aurora.
WATCHLIST_SKY = 0.70


@dataclass(slots=True)
class SourceInfo:
    """Provenance for one upstream product."""

    name: str
    status: str
    fetched_at: datetime | None = None
    issued_at: datetime | None = None
    detail: str = ""


@dataclass(slots=True)
class NightOutlook:
    """One night at one city."""

    night: str
    city_key: str
    peak: HourScore
    hours: list[HourScore]
    window_start: datetime | None
    window_end: datetime | None
    qualifies: bool
    dark_hours: int
    truncated: bool = False

    @property
    def score(self) -> float:
        return self.peak.score

    @property
    def window_hours(self) -> int:
        if self.window_start is None or self.window_end is None:
            return 0
        return int((self.window_end - self.window_start).total_seconds() // 3600) + 1

    @property
    def best_cluster(self) -> ClusterSky | None:
        return self.peak.cluster


@dataclass(slots=True)
class CityOutlook:
    """Every scored night for one city."""

    city: City
    nights: list[NightOutlook]
    points_used: int
    points_failed: list[str] = field(default_factory=list)

    @property
    def best(self) -> NightOutlook | None:
        return max(self.nights, key=lambda n: n.score, default=None)


@dataclass(slots=True)
class ClearSkyWatch:
    """A long-range night whose *cloud* outlook looks good, aurora unknown."""

    city_key: str
    night: str
    sky: float
    dark_hours: int
    anchor: str
    lead_days: float


@dataclass(slots=True)
class AuroraWatch:
    """The result of a run."""

    generated_at: datetime
    threshold: float
    days: int
    cities: list[CityOutlook]
    alerts: list[NightOutlook]
    clear_sky_watchlist: list[ClearSkyWatch]
    sources: list[SourceInfo]
    warnings: list[str]
    version: str = __version__

    def city(self, key: str) -> CityOutlook:
        for outlook in self.cities:
            if outlook.city.key == key:
                return outlook
        raise KeyError(key)


@dataclass(slots=True)
class _SpaceWeather:
    kp_forecast: swpc.KpForecast | None = None
    outlook: swpc.Outlook27Day | None = None
    ovation: swpc.OvationNowcast | None = None
    solar_wind: swpc.SolarWind | None = None
    alerts: swpc.SpaceWeatherAlerts | None = None


def _load_space_weather(sources: list[SourceInfo], warnings: list[str]) -> _SpaceWeather:
    state = _SpaceWeather()
    loaders = (
        ("SWPC 3-hourly Kp forecast", "kp_forecast", swpc.fetch_kp_forecast),
        ("SWPC 27-day outlook", "outlook", swpc.fetch_27day_outlook),
        ("SWPC OVATION nowcast", "ovation", swpc.fetch_ovation),
        ("SWPC propagated solar wind", "solar_wind", swpc.fetch_solar_wind),
        ("SWPC alerts", "alerts", swpc.fetch_alerts),
    )
    for name, attribute, loader in loaders:
        try:
            value = loader()
        except SourceError as exc:
            sources.append(SourceInfo(name, "unavailable", detail=str(exc)))
            warnings.append(f"{name} unavailable: {exc}")
            continue
        setattr(state, attribute, value)
        sources.append(
            SourceInfo(
                name,
                "ok",
                fetched_at=getattr(value, "fetched_at", None),
                issued_at=getattr(value, "issued", None)
                or getattr(value, "forecast_time", None),
            )
        )
    return state


def _load_forecasts(
    city: City, warnings: list[str]
) -> tuple[dict[str, PointForecast], list[str]]:
    forecasts: dict[str, PointForecast] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=MET_CONCURRENCY) as pool:
        results = list(
            pool.map(
                lambda point: (point, _safe_fetch_point(point)),
                city.points,
            )
        )
    for point, forecast in results:
        if forecast is None:
            failed.append(point.name)
            warnings.append(f"{city.name}: no cloud forecast for {point.name}")
        else:
            forecasts[point.name] = forecast
    return forecasts, failed


def _safe_fetch_point(point):
    try:
        return fetch_point(point)
    except SourceError:
        return None
    except Exception:  # network stacks raise a wide variety of things
        return None


def _hour_range(now: datetime, days: int) -> list[datetime]:
    start = now.replace(minute=0, second=0, microsecond=0)
    return [start + timedelta(hours=h) for h in range(days * 24 + 1)]


def _find_window(
    hours: list[HourScore], threshold: float
) -> tuple[datetime | None, datetime | None]:
    """Longest run of >= MIN_WINDOW_HOURS consecutive hours at or above threshold."""
    best: tuple[int, datetime, datetime] | None = None
    run: list[HourScore] = []
    for hour in hours:
        if hour.score >= threshold:
            run.append(hour)
            continue
        if len(run) >= MIN_WINDOW_HOURS and (best is None or len(run) > best[0]):
            best = (len(run), run[0].time, run[-1].time)
        run = []
    if len(run) >= MIN_WINDOW_HOURS and (best is None or len(run) > best[0]):
        best = (len(run), run[0].time, run[-1].time)
    if best is None:
        return None, None
    return best[1], best[2]


def _score_city(
    city: City,
    now: datetime,
    hours: list[datetime],
    space: _SpaceWeather,
    threshold: float,
    warnings: list[str],
) -> CityOutlook:
    forecasts, failed = _load_forecasts(city, warnings)

    scored: list[HourScore] = []
    for when in hours:
        geometry = sky_geometry(city.lat, city.lon, 0.0, when)
        aurora = aurora_potential(
            when,
            now,
            city,
            kp_forecast=space.kp_forecast,
            outlook=space.outlook,
            ovation=space.ovation,
            solar_wind=space.solar_wind,
            alerts=space.alerts,
        )
        if not geometry.is_dark_enough:
            # Cheap path: the darkness gate already decides this hour.
            scored.append(
                score_hour(when, now, city, aurora, None)
            )
            continue

        points = score_points(forecasts, when)
        if not points:
            scored.append(score_hour(when, now, city, aurora, None))
            continue
        cluster = best_cluster(points)
        count, span = clear_footprint(points)
        scored.append(
            score_hour(
                when,
                now,
                city,
                aurora,
                cluster,
                clear_point_count=count,
                clear_span_km=span,
                any_interpolated=any(p.interpolated for p in points),
            )
        )

    by_night: dict[str, list[HourScore]] = {}
    for hour in scored:
        by_night.setdefault(night_key(hour.time, city), []).append(hour)

    horizon_end = hours[-1]
    nights: list[NightOutlook] = []
    for night, night_hours in sorted(by_night.items()):
        night_hours.sort(key=lambda h: h.time)
        dark = [h for h in night_hours if h.geometry.is_dark_enough]
        peak = max(night_hours, key=lambda h: h.score)
        start, end = _find_window(night_hours, threshold)
        # The final night is usually clipped by the horizon. Scoring a fragment
        # of a night as if it were the whole night would understate it, so it is
        # reported but never allowed to alert.
        truncated = night_hours[-1].time >= horizon_end and len(dark) < 4
        nights.append(
            NightOutlook(
                night=night,
                city_key=city.key,
                peak=peak,
                hours=night_hours,
                window_start=start,
                window_end=end,
                qualifies=start is not None and not truncated,
                dark_hours=len(dark),
                truncated=truncated,
            )
        )

    return CityOutlook(
        city=city,
        nights=nights,
        points_used=len(forecasts),
        points_failed=failed,
    )


def _watchlist(outlooks: list[CityOutlook]) -> list[ClearSkyWatch]:
    """Long-range nights where the *cloud* outlook is promising.

    Days 4-5 cannot alert, because no aurora forecast supports them. They can
    still tell you where to look again in two days, which is the actionable
    thing at that range.
    """
    watch: list[ClearSkyWatch] = []
    for outlook in outlooks:
        for night in outlook.nights:
            dark = [h for h in night.hours if h.geometry.is_dark_enough and h.cluster]
            long_range = [h for h in dark if h.lead_hours > LONG_RANGE_HOURS]
            if len(long_range) < MIN_WINDOW_HOURS:
                continue
            best = max(long_range, key=lambda h: h.cluster.sky)  # type: ignore[union-attr]
            if best.cluster is None or best.cluster.sky < WATCHLIST_SKY:
                continue
            watch.append(
                ClearSkyWatch(
                    city_key=outlook.city.key,
                    night=night.night,
                    sky=round(best.cluster.sky, 3),
                    dark_hours=len(dark),
                    anchor=best.cluster.anchor.name,
                    lead_days=round(best.lead_hours / 24.0, 1),
                )
            )
    watch.sort(key=lambda w: -w.sky)
    return watch


def run_aurora_watch(
    cities: Sequence[str] | None = None,
    days: int = DEFAULT_DAYS,
    threshold: float = DEFAULT_THRESHOLD,
    now: datetime | None = None,
) -> AuroraWatch:
    """Check the next ``days`` days for high-quality aurora viewing windows.

    Args:
        cities: City keys to check. Defaults to all four tracked cities.
        days: Forecast horizon. Beyond 3 days no aurora forecast exists, so
            those nights are score-capped and routed to the clear-sky watchlist.
        threshold: Score at or above which a night is reported as an alert.
        now: Reference time, for deterministic testing. Defaults to now (UTC).

    Returns:
        An :class:`AuroraWatch` with per-city nightly breakdowns, the alerting
        nights, a long-range clear-sky watchlist, source provenance, and any
        warnings raised by degraded sources.
    """
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected = [get_city(key) for key in cities] if cities else list(all_cities())

    warnings: list[str] = []
    sources: list[SourceInfo] = []
    space = _load_space_weather(sources, warnings)
    if space.kp_forecast is None and space.outlook is None:
        warnings.append(
            "No geomagnetic forecast available at all - aurora potential cannot "
            "be estimated and every score below is a floor, not an estimate."
        )

    hours = _hour_range(reference, days)
    outlooks = [
        _score_city(city, reference, hours, space, threshold, warnings)
        for city in selected
    ]

    alerts = [
        night
        for outlook in outlooks
        for night in outlook.nights
        if night.qualifies and night.score >= threshold
    ]
    alerts.sort(key=lambda n: (-n.score, n.night))

    sources.append(
        SourceInfo(
            "MET Norway Locationforecast",
            "ok" if any(o.points_used for o in outlooks) else "unavailable",
            detail=f"{sum(o.points_used for o in outlooks)} viewing points across "
            f"{len(outlooks)} cities",
        )
    )

    return AuroraWatch(
        generated_at=reference,
        threshold=threshold,
        days=days,
        cities=outlooks,
        alerts=alerts,
        clear_sky_watchlist=_watchlist(outlooks),
        sources=sources,
        warnings=warnings,
    )
