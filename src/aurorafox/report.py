"""Human-readable rendering of an :class:`~aurorafox.watch.AuroraWatch`.

The report leads with the verdict, because on most nights the answer is "no" and
burying that under tables wastes the reader's time. It then explains *why* each
night failed, which is the part that tells you whether to re-run tomorrow.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .locations import City, get_city
from .scoring.combine import LONG_RANGE_SCORE_CAP
from .watch import MIN_WINDOW_HOURS, AuroraWatch, CityOutlook, NightOutlook

BAR_WIDTH = 10


def _local(when: datetime, city: City) -> str:
    return when.astimezone(ZoneInfo(city.timezone)).strftime("%H:%M")


def _night_label(night: str) -> str:
    return datetime.fromisoformat(night).strftime("%a %d %b")


def _bar(score: float) -> str:
    filled = int(round((score - 1.0) / 9.0 * BAR_WIDTH))
    return "#" * filled + "." * (BAR_WIDTH - filled)


def _window(night: NightOutlook, city: City) -> str:
    if night.window_start is None or night.window_end is None:
        return "-"
    return (
        f"{_local(night.window_start, city)}-{_local(night.window_end, city)}"
        f" ({night.window_hours}h)"
    )


def _cluster_line(night: NightOutlook, city: City) -> str:
    cluster = night.best_cluster
    if cluster is None:
        return "no coherent clear region"
    others = [n for n in cluster.member_names if n != cluster.anchor.name][:3]
    point = next((p for p in city.points if p.name == cluster.anchor.name), None)
    drive = ""
    if point is not None and point.drive_minutes > 0:
        drive = f", ~{point.drive_minutes} min from {city.name}"
    tail = f" with {', '.join(others)}" if others else ""
    return (
        f"{cluster.anchor.name}{drive} - {cluster.sky * 100:.0f}% clear across "
        f"{cluster.span_km:.0f} km{tail}"
    )


def render_night(night: NightOutlook, city: City, threshold: float) -> list[str]:
    peak = night.peak
    flag = " ALERT" if night.qualifies and night.score >= threshold else ""
    if night.truncated:
        flag = " (partial night at the forecast horizon)"
    elif not night.qualifies and night.score >= threshold:
        # The peak clears the bar but nothing sustains it. Say so, rather than
        # printing a high score next to a blank window and leaving the reader
        # to guess.
        flag = f" (peak only - under {MIN_WINDOW_HOURS}h sustained, not an alert)"
    lines = [
        f"  {_night_label(night.night):<11} {night.score:>5.2f}  "
        f"[{_bar(night.score)}]  peak {_local(peak.time, city)}"
        f"  window {_window(night, city)}{flag}"
    ]
    if night.dark_hours == 0:
        lines.append("               never dark enough - sun stays above -6 deg")
        return lines
    lines.append(f"               sky: {_cluster_line(night, city)}")
    kp = f"Kp {peak.aurora.kp:.2f}" if peak.aurora.kp is not None else "Kp n/a"
    lines.append(
        f"               aurora: {kp} ({peak.aurora.kp_source}); "
        f"{peak.aurora.geometry_note}"
    )
    moon = peak.geometry
    moon_note = (
        f"moon {moon.moon_illumination * 100:.0f}% at {moon.moon_altitude_deg:+.0f} deg"
        if moon.moon_altitude_deg > 0
        else "moon below horizon"
    )
    lines.append(
        f"               dark: {peak.geometry.darkness * 100:.0f}% "
        f"(sun {peak.geometry.sun_altitude_deg:+.0f} deg), {moon_note}"
    )
    lines.append(
        f"               limited by: {peak.limiting_factor}"
        + (f"  [capped at {LONG_RANGE_SCORE_CAP:.0f} - no Kp forecast this far out]"
           if peak.capped else "")
    )
    return lines


def render_city(outlook: CityOutlook, threshold: float) -> list[str]:
    city = outlook.city
    header = (
        f"{city.name.upper()} ({city.country})  "
        f"geomagnetic lat {city.cgm_latitude:.1f} deg, "
        f"{outlook.points_used} viewing sites"
    )
    lines = [header, "-" * len(header)]
    if outlook.points_failed:
        lines.append(f"  ! no forecast for: {', '.join(outlook.points_failed)}")
    for night in outlook.nights:
        lines.extend(render_night(night, city, threshold))
        lines.append("")
    return lines


def render(watch: AuroraWatch) -> str:
    """Render a full report."""
    generated = watch.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = [
        "=" * 72,
        f"AURORA WATCH  -  next {watch.days} days  -  generated {generated}",
        f"alert threshold {watch.threshold:.1f}/10",
        "=" * 72,
        "",
    ]

    if watch.alerts:
        out.append(f"** {len(watch.alerts)} NIGHT(S) AT OR ABOVE {watch.threshold:.0f}/10 **")
        out.append("")
        for night in watch.alerts:
            city = get_city(night.city_key)
            out.append(
                f"  {city.name}  {_night_label(night.night)}  "
                f"{night.score:.2f}/10  {_window(night, city)}"
            )
            out.append(f"      -> {_cluster_line(night, city)}")
        out.append("")
    else:
        out.append(
            f"No night reaches {watch.threshold:.1f}/10 in the next {watch.days} days."
        )
        best = [
            (o.best.score, o.city.name, o.best)
            for o in watch.cities
            if o.best is not None
        ]
        if best:
            score, name, night = max(best)
            city = get_city(night.city_key)
            reason = (
                f"peaked above {watch.threshold:.0f} for under {MIN_WINDOW_HOURS}h"
                if score >= watch.threshold and not night.qualifies
                else f"limited by {night.peak.limiting_factor}"
            )
            out.append(
                f"Best on offer: {name} on {_night_label(night.night)} "
                f"at {score:.2f}/10 - {reason}."
            )
        out.append("")

    if watch.clear_sky_watchlist:
        out.append("CLEAR-SKY WATCHLIST (days 4-5: cloud looks good, aurora unknowable yet)")
        for item in watch.clear_sky_watchlist:
            city = get_city(item.city_key)
            out.append(
                f"  {city.name:<11} {_night_label(item.night)}  "
                f"{item.sky * 100:.0f}% clear near {item.anchor}  "
                f"(+{item.lead_days:.1f} d - re-run in 2 days)"
            )
        out.append("")

    for outlook in watch.cities:
        out.extend(render_city(outlook, watch.threshold))

    out.append("SOURCES")
    for source in watch.sources:
        stamp = ""
        if source.issued_at:
            stamp = f" issued {source.issued_at:%Y-%m-%d %H:%M UTC}"
        elif source.fetched_at:
            stamp = f" fetched {source.fetched_at:%H:%M UTC}"
        detail = f" - {source.detail}" if source.detail else ""
        out.append(f"  [{source.status}] {source.name}{stamp}{detail}")

    if watch.warnings:
        out.append("")
        out.append("WARNINGS")
        for warning in watch.warnings:
            out.append(f"  ! {warning}")

    return "\n".join(out)


def render_explain(outlook: CityOutlook) -> str:
    """Hour-by-hour factor breakdown for one city."""
    city = outlook.city
    out = [f"{city.name} - hour by hour (local time {city.timezone})", ""]
    out.append(
        f"{'local':>6} {'score':>6} {'A':>6} {'Aadj':>6} {'sky':>6} {'Sadj':>6} "
        f"{'dark':>6} {'moon':>6} {'Kp':>5}  cluster / note"
    )
    for night in outlook.nights:
        out.append(f"-- night of {night.night} --")
        for hour in night.hours:
            if not hour.geometry.is_dark_enough:
                continue
            kp = f"{hour.aurora.kp:.2f}" if hour.aurora.kp is not None else "  -  "
            anchor = hour.cluster.anchor.name if hour.cluster else "none eligible"
            out.append(
                f"{_local(hour.time, city):>6} {hour.score:>6.2f} "
                f"{hour.aurora.potential:>6.3f} {hour.aurora_adjusted:>6.3f} "
                f"{hour.sky:>6.3f} {hour.sky_adjusted:>6.3f} "
                f"{hour.geometry.darkness:>6.3f} {hour.moon:>6.3f} {kp:>5}  {anchor}"
            )
    return "\n".join(out)
