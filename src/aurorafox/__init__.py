"""AuroraFox - on-demand aurora visibility watch for northern Europe."""

from .locations import CITIES, City, ViewingPoint, all_cities, get_city
from .version import __version__
from .watch import (
    AuroraWatch,
    CityOutlook,
    ClearSkyWatch,
    NightOutlook,
    SourceInfo,
    run_aurora_watch,
)

__all__ = [
    "AuroraWatch",
    "CITIES",
    "City",
    "CityOutlook",
    "ClearSkyWatch",
    "NightOutlook",
    "SourceInfo",
    "ViewingPoint",
    "__version__",
    "all_cities",
    "get_city",
    "run_aurora_watch",
]
