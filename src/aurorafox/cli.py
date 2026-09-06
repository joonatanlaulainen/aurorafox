"""Command-line entry point: ``aurora-watch``."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone

from .locations import CITIES
from .report import render, render_explain
from .version import __version__
from .watch import AuroraWatch, DEFAULT_DAYS, DEFAULT_THRESHOLD, run_aurora_watch


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _to_json(watch: AuroraWatch) -> str:
    payload = {
        "version": watch.version,
        "generated_at": watch.generated_at,
        "threshold": watch.threshold,
        "days": watch.days,
        "alerts": [
            {
                "city": night.city_key,
                "night": night.night,
                "score": night.score,
                "window_start": night.window_start,
                "window_end": night.window_end,
                "window_hours": night.window_hours,
                "anchor": night.best_cluster.anchor.name if night.best_cluster else None,
                "sites": list(night.best_cluster.member_names) if night.best_cluster else [],
                "cluster_sky": night.best_cluster.sky if night.best_cluster else None,
                "cluster_span_km": night.best_cluster.span_km if night.best_cluster else None,
                "kp": night.peak.aurora.kp,
                "kp_source": night.peak.aurora.kp_source,
                "limiting_factor": night.peak.limiting_factor,
            }
            for night in watch.alerts
        ],
        "clear_sky_watchlist": [dataclasses.asdict(w) for w in watch.clear_sky_watchlist],
        "cities": [
            {
                "key": outlook.city.key,
                "name": outlook.city.name,
                "cgm_latitude": outlook.city.cgm_latitude,
                "points_used": outlook.points_used,
                "points_failed": outlook.points_failed,
                "nights": [
                    {
                        "night": night.night,
                        "score": night.score,
                        "qualifies": night.qualifies,
                        "truncated": night.truncated,
                        "dark_hours": night.dark_hours,
                        "peak_time": night.peak.time,
                        "window_start": night.window_start,
                        "window_end": night.window_end,
                        "tier": night.peak.tier.name,
                        "aurora_potential": round(night.peak.aurora.potential, 4),
                        "aurora_adjusted": round(night.peak.aurora_adjusted, 4),
                        "sky": round(night.peak.sky, 4),
                        "sky_adjusted": round(night.peak.sky_adjusted, 4),
                        "darkness": round(night.peak.geometry.darkness, 4),
                        "moon_factor": round(night.peak.moon, 4),
                        "moon_illumination": round(night.peak.geometry.moon_illumination, 3),
                        "kp": night.peak.aurora.kp,
                        "kp_source": night.peak.aurora.kp_source,
                        "site_position": night.peak.aurora.site_position,
                        "anchor": (
                            night.best_cluster.anchor.name if night.best_cluster else None
                        ),
                        "cluster_sites": (
                            list(night.best_cluster.member_names)
                            if night.best_cluster
                            else []
                        ),
                        "cluster_span_km": (
                            round(night.best_cluster.span_km, 1)
                            if night.best_cluster
                            else None
                        ),
                        "clear_point_count": night.peak.clear_point_count,
                        "clear_span_km": round(night.peak.clear_span_km, 1),
                        "capped": night.peak.capped,
                        "limiting_factor": night.peak.limiting_factor,
                    }
                    for night in outlook.nights
                ],
            }
            for outlook in watch.cities
        ],
        "sources": [dataclasses.asdict(s) for s in watch.sources],
        "warnings": watch.warnings,
    }
    return json.dumps(payload, default=_json_default, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aurora-watch",
        description=(
            "Check the next few days for high-quality aurora viewing windows "
            "around Tromso, Kiruna, Rovaniemi and Reykjavik."
        ),
    )
    parser.add_argument(
        "--city",
        action="append",
        choices=sorted(CITIES),
        help="Restrict to one city (repeatable). Default: all four.",
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Forecast horizon.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Score at or above which a night is reported as an alert.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Append an hour-by-hour factor breakdown for each city.",
    )
    parser.add_argument(
        "--at",
        metavar="ISO8601",
        help="Score as if it were this time (for testing). Defaults to now.",
    )
    parser.add_argument("--version", action="version", version=f"aurorafox {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    reference = None
    if args.at:
        reference = datetime.fromisoformat(args.at.replace("Z", "+00:00"))
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)

    watch = run_aurora_watch(
        cities=args.city,
        days=args.days,
        threshold=args.threshold,
        now=reference,
    )

    if args.json:
        print(_to_json(watch))
    else:
        print(render(watch))
        if args.explain:
            for outlook in watch.cities:
                print()
                print(render_explain(outlook))

    # Exit 0 when something is worth acting on, 1 when nothing is - handy for
    # wiring this into a shell alias or a notification hook.
    return 0 if watch.alerts else 1


if __name__ == "__main__":
    sys.exit(main())
