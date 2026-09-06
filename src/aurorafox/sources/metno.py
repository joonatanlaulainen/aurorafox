"""MET Norway Locationforecast 2.0 client.

The service returns a time series whose *resolution changes partway through*:
hourly for roughly the first 60-65 hours, then 6-hourly out to about nine days.
It also drops fields at long range - ``fog_area_fraction`` is present in the
near term and simply absent beyond the hourly section.

Both facts are load-bearing for a 5-day product, so the parser preserves them
rather than smoothing them away: every sample records the native step it came
from, and every field is ``float | None`` so a missing value can be handled as
unknown instead of silently read as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..locations import ViewingPoint
from .http import Response, SourceError, fetch

BASE_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"

# MET asks for coordinates truncated to 4 decimals so their cache is effective.
COORD_PRECISION = 4


@dataclass(frozen=True, slots=True)
class WeatherSample:
    """Cloud and moisture state at one instant."""

    time: datetime
    cloud_total: float | None
    cloud_low: float | None
    cloud_medium: float | None
    cloud_high: float | None
    fog: float | None
    relative_humidity: float | None
    precipitation_mm: float | None
    native_step_hours: float
    interpolated: bool = False

    @property
    def has_fog_field(self) -> bool:
        return self.fog is not None


@dataclass(slots=True)
class PointForecast:
    """A viewing point's forecast, resampled onto a uniform hourly grid."""

    point: ViewingPoint
    samples: dict[datetime, WeatherSample]
    updated_at: datetime | None
    from_cache: bool

    def at(self, when: datetime) -> WeatherSample | None:
        return self.samples.get(when.replace(minute=0, second=0, microsecond=0))


def _url(point: ViewingPoint) -> str:
    return (
        f"{BASE_URL}?lat={round(point.lat, COORD_PRECISION)}"
        f"&lon={round(point.lon, COORD_PRECISION)}"
        f"&altitude={int(point.altitude_m)}"
    )


def _parse_time(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def _extract(entry: dict) -> tuple[datetime, dict, float | None]:
    details = entry.get("data", {}).get("instant", {}).get("details", {})
    precip = None
    for window in ("next_1_hours", "next_6_hours"):
        block = entry.get("data", {}).get(window, {}).get("details", {})
        if "precipitation_amount" in block:
            precip = float(block["precipitation_amount"])
            # next_6_hours totals cover six times the span; express per hour so
            # near and far samples are comparable.
            if window == "next_6_hours":
                precip /= 6.0
            break
    return _parse_time(entry["time"]), details, precip


def _blend(a: float | None, b: float | None, weight: float) -> float | None:
    if a is None or b is None:
        return None
    return a + (b - a) * weight


def parse(payload: dict, point: ViewingPoint, response: Response) -> PointForecast:
    """Turn a Locationforecast payload into an hourly :class:`PointForecast`."""
    try:
        series = payload["properties"]["timeseries"]
    except (KeyError, TypeError) as exc:
        raise SourceError(f"unexpected locationforecast payload for {point.name}") from exc
    if not series:
        raise SourceError(f"empty locationforecast timeseries for {point.name}")

    raw: list[tuple[datetime, WeatherSample]] = []
    for index, entry in enumerate(series):
        when, details, precip = _extract(entry)
        step = 1.0
        if index + 1 < len(series):
            step = (_parse_time(series[index + 1]["time"]) - when).total_seconds() / 3600.0
        raw.append(
            (
                when,
                WeatherSample(
                    time=when,
                    cloud_total=details.get("cloud_area_fraction"),
                    cloud_low=details.get("cloud_area_fraction_low"),
                    cloud_medium=details.get("cloud_area_fraction_medium"),
                    cloud_high=details.get("cloud_area_fraction_high"),
                    fog=details.get("fog_area_fraction"),
                    relative_humidity=details.get("relative_humidity"),
                    precipitation_mm=precip,
                    native_step_hours=step,
                ),
            )
        )

    samples: dict[datetime, WeatherSample] = {}
    for index, (when, sample) in enumerate(raw):
        samples[when] = sample
        if index + 1 >= len(raw):
            continue
        next_time, next_sample = raw[index + 1]
        gap = int((next_time - when).total_seconds() // 3600)
        # Fill the 6-hourly long-range section onto the hourly grid. These are
        # flagged so the combiner can discount them; interpolating cloud fields
        # is a convenience for lining up night windows, not added information.
        for offset in range(1, gap):
            weight = offset / gap
            filled = when + timedelta(hours=offset)
            samples[filled] = WeatherSample(
                time=filled,
                cloud_total=_blend(sample.cloud_total, next_sample.cloud_total, weight),
                cloud_low=_blend(sample.cloud_low, next_sample.cloud_low, weight),
                cloud_medium=_blend(sample.cloud_medium, next_sample.cloud_medium, weight),
                cloud_high=_blend(sample.cloud_high, next_sample.cloud_high, weight),
                fog=_blend(sample.fog, next_sample.fog, weight),
                relative_humidity=_blend(
                    sample.relative_humidity, next_sample.relative_humidity, weight
                ),
                precipitation_mm=sample.precipitation_mm,
                native_step_hours=sample.native_step_hours,
                interpolated=True,
            )

    updated_at = None
    meta_updated = payload.get("properties", {}).get("meta", {}).get("updated_at")
    if meta_updated:
        updated_at = _parse_time(meta_updated)

    return PointForecast(
        point=point,
        samples=samples,
        updated_at=updated_at,
        from_cache=response.from_cache,
    )


def fetch_point(point: ViewingPoint) -> PointForecast:
    """Fetch and parse the forecast for one viewing point."""
    response = fetch(_url(point), default_ttl=1800.0)
    return parse(response.json(), point, response)
