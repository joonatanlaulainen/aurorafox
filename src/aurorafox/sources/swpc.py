"""NOAA Space Weather Prediction Center clients.

The single most important thing this module encodes is *where each product's
skill actually ends*, because the horizons differ far more than the marketing
around them suggests:

``noaa-planetary-k-index-forecast.json``
    3-hourly Kp, observed and predicted, but only about **72 hours** ahead.
``ovation_aurora_latest.json``
    A 1x1 degree global grid of aurora probability - but a **nowcast**, valid
    for the 30-90 minutes named in its own ``Forecast Time`` field, not a
    forecast product.
``geospace/propagated-solar-wind-1-hour.json``
    Live Bz/Bt/speed/density already propagated to the magnetopause. Meaningful
    for the next hour or so. (The commonly cited ``solar-wind/mag-1-day.json``
    and ``plasma-1-day.json`` paths return 404; this is the working product.)
``27-day-outlook.txt``
    Daily *largest* Kp from coronal-hole recurrence. The only aurora signal that
    exists past 72 hours, and it can be a week old. Used as a weak upper bound
    and nothing more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..geo import clamp
from .http import SourceError, fetch

KP_FORECAST_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
OVATION_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
SOLAR_WIND_URL = (
    "https://services.swpc.noaa.gov/products/geospace/propagated-solar-wind-1-hour.json"
)
OUTLOOK_27DAY_URL = "https://services.swpc.noaa.gov/text/27-day-outlook.txt"
ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"

# How far the 3-hourly Kp product actually reaches. Beyond this we fall back to
# the 27-day outlook, at much lower confidence.
KP_FORECAST_HORIZON_HOURS = 78


def _utc(raw: str) -> datetime:
    text = raw.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rows(payload) -> list[dict]:
    """Normalise SWPC's two shapes: list-of-dicts, or header row plus arrays."""
    if not payload:
        return []
    if isinstance(payload[0], dict):
        return list(payload)
    header = [str(h) for h in payload[0]]
    return [dict(zip(header, row, strict=False)) for row in payload[1:]]


@dataclass(slots=True)
class KpForecast:
    """3-hourly planetary Kp, observed and predicted."""

    entries: list[tuple[datetime, float, bool]]  # (time, kp, is_predicted)
    fetched_at: datetime

    @property
    def horizon_end(self) -> datetime | None:
        return max((t for t, _, _ in self.entries), default=None)

    def at(self, when: datetime) -> float | None:
        """Kp for the 3-hour bin containing ``when``, or None if out of range."""
        best: tuple[timedelta, float] | None = None
        for time_tag, kp, _ in self.entries:
            # Each entry labels the start of a 3-hour bin.
            if time_tag <= when < time_tag + timedelta(hours=3):
                return kp
            delta = abs(time_tag - when)
            if best is None or delta < best[0]:
                best = (delta, kp)
        if best is not None and best[0] <= timedelta(hours=3):
            return best[1]
        return None

    def recent_observed(self, now: datetime, hours: int = 12) -> list[float]:
        cutoff = now - timedelta(hours=hours)
        return [kp for t, kp, pred in self.entries if not pred and cutoff <= t <= now]


@dataclass(slots=True)
class OvationNowcast:
    """A 1-degree grid of aurora probability, valid for a short window."""

    observation_time: datetime
    forecast_time: datetime
    grid: dict[tuple[int, int], float]  # (lon 0..359, lat -90..90) -> percent

    def probability(self, lat: float, lon: float) -> float | None:
        """Bilinear interpolation of aurora probability at a location."""
        lon360 = lon % 360.0
        lon0, lat0 = int(lon360 // 1), int(lat // 1)
        fx, fy = lon360 - lon0, lat - lat0
        corners = []
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            value = self.grid.get(((lon0 + dx) % 360, lat0 + dy))
            if value is None:
                return None
            corners.append(value)
        c00, c10, c01, c11 = corners
        return (
            c00 * (1 - fx) * (1 - fy)
            + c10 * fx * (1 - fy)
            + c01 * (1 - fx) * fy
            + c11 * fx * fy
        )

    def is_valid_for(self, when: datetime, window_hours: float = 3.0) -> bool:
        return abs((when - self.forecast_time).total_seconds()) <= window_hours * 3600.0


@dataclass(slots=True)
class SolarWind:
    """Recent propagated solar-wind conditions at the magnetopause."""

    latest_time: datetime
    bz: float | None
    bt: float | None
    speed: float | None
    density: float | None
    mean_bz_30min: float | None

    @property
    def is_southward(self) -> bool:
        return self.mean_bz_30min is not None and self.mean_bz_30min < -2.0


@dataclass(slots=True)
class Outlook27Day:
    """Daily largest-Kp outlook, the only signal available past ~72 h."""

    issued: datetime | None
    largest_kp: dict[str, float]  # ISO date -> Kp
    fetched_at: datetime

    def at(self, when: datetime) -> float | None:
        return self.largest_kp.get(when.astimezone(timezone.utc).date().isoformat())

    def age_days(self, now: datetime) -> float | None:
        if self.issued is None:
            return None
        return (now - self.issued).total_seconds() / 86400.0


@dataclass(slots=True)
class SpaceWeatherAlerts:
    """Active SWPC watches, warnings and alerts."""

    messages: list[tuple[datetime, str, str]] = field(default_factory=list)

    def active_geomagnetic(self, now: datetime, within_hours: float = 48.0) -> list[str]:
        """Recent geomagnetic watches/warnings, summarised to their headline."""
        out = []
        for issued, _product_id, message in self.messages:
            if (now - issued).total_seconds() > within_hours * 3600.0:
                continue
            if not re.search(r"\b(geomagnetic|G[1-5]|CME|K-index)\b", message, re.I):
                continue
            for line in message.splitlines():
                if line.startswith(("WATCH:", "WARNING:", "ALERT:", "EXTENDED WARNING:")):
                    out.append(line.strip())
                    break
        return out

    def max_watch_level(self, now: datetime, within_hours: float = 48.0) -> int:
        """Highest G-level mentioned in a recent geomagnetic message (0 if none)."""
        level = 0
        for headline in self.active_geomagnetic(now, within_hours):
            for match in re.finditer(r"\bG([1-5])\b", headline):
                level = max(level, int(match.group(1)))
        return level


def fetch_kp_forecast() -> KpForecast:
    response = fetch(KP_FORECAST_URL, default_ttl=900.0)
    entries: list[tuple[datetime, float, bool]] = []
    for row in _rows(response.json()):
        try:
            entries.append(
                (
                    _utc(str(row["time_tag"])),
                    float(row["kp"]),
                    str(row.get("observed", "")).lower() != "observed",
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not entries:
        raise SourceError("no usable rows in the planetary K-index forecast")
    entries.sort()
    return KpForecast(entries=entries, fetched_at=response.fetched_at)


def fetch_ovation() -> OvationNowcast:
    response = fetch(OVATION_URL, default_ttl=300.0)
    payload = response.json()
    try:
        grid = {(int(lon), int(lat)): float(value) for lon, lat, value in payload["coordinates"]}
        return OvationNowcast(
            observation_time=_utc(payload["Observation Time"]),
            forecast_time=_utc(payload["Forecast Time"]),
            grid=grid,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("unexpected OVATION payload") from exc


def fetch_solar_wind() -> SolarWind:
    response = fetch(SOLAR_WIND_URL, default_ttl=300.0)
    rows = _rows(response.json())
    usable = [r for r in rows if r.get("bz") is not None and r.get("time_tag")]
    if not usable:
        raise SourceError("no usable rows in the propagated solar wind product")
    latest = usable[-1]
    recent = [float(r["bz"]) for r in usable[-30:] if r.get("bz") is not None]

    def maybe(key: str) -> float | None:
        value = latest.get(key)
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    return SolarWind(
        latest_time=_utc(str(latest["time_tag"])),
        bz=maybe("bz"),
        bt=maybe("bt"),
        speed=maybe("speed"),
        density=maybe("density"),
        mean_bz_30min=sum(recent) / len(recent) if recent else None,
    )


_OUTLOOK_ROW = re.compile(
    r"^(\d{4})\s+(\w{3})\s+(\d{1,2})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$"
)
_MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_MONTHS = {name: index for index, name in enumerate(_MONTH_NAMES, start=1)}


def fetch_27day_outlook() -> Outlook27Day:
    response = fetch(OUTLOOK_27DAY_URL, default_ttl=3600.0)
    issued: datetime | None = None
    largest: dict[str, float] = {}
    for line in response.text.splitlines():
        if issued is None and line.startswith(":Issued:"):
            match = re.search(r"(\d{4})\s+(\w{3})\s+(\d{1,2})\s+(\d{2})(\d{2})", line)
            if match:
                year, mon, day, hour, minute = match.groups()
                issued = datetime(
                    int(year), _MONTHS[mon], int(day), int(hour), int(minute),
                    tzinfo=timezone.utc,
                )
            continue
        match = _OUTLOOK_ROW.match(line.strip())
        if not match:
            continue
        year, mon, day, _flux, _ap, kp = match.groups()
        if mon not in _MONTHS:
            continue
        key = datetime(int(year), _MONTHS[mon], int(day), tzinfo=timezone.utc).date()
        largest[key.isoformat()] = float(kp)
    if not largest:
        raise SourceError("no usable rows in the 27-day outlook")
    return Outlook27Day(issued=issued, largest_kp=largest, fetched_at=response.fetched_at)


def fetch_alerts() -> SpaceWeatherAlerts:
    response = fetch(ALERTS_URL, default_ttl=600.0)
    messages: list[tuple[datetime, str, str]] = []
    for row in _rows(response.json()):
        try:
            messages.append(
                (
                    _utc(str(row["issue_datetime"])),
                    str(row.get("product_id", "")),
                    str(row.get("message", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    messages.sort(reverse=True)
    return SpaceWeatherAlerts(messages=messages)


def solar_wind_boost(wind: SolarWind) -> float:
    """A 0..1 enhancement factor from live solar wind, for the next ~3 hours.

    Southward Bz is what actually opens the magnetosphere; speed modulates how
    much energy comes through once it is open. Deliberately bounded - this is a
    nudge on top of the Kp-driven estimate, not a replacement for it.
    """
    if wind.mean_bz_30min is None:
        return 0.0
    # -2 nT does nothing; -10 nT and beyond saturates.
    bz_term = clamp((-wind.mean_bz_30min - 2.0) / 8.0)
    speed_term = clamp(((wind.speed or 400.0) - 400.0) / 300.0)
    return clamp(0.75 * bz_term + 0.25 * bz_term * speed_term)
