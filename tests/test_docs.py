"""Keep docs/interpretation in step with the code.

These docs exist so that an LLM handed a result - with no access to this
repository - can interpret it correctly. That only works if the numbers in them
are true. Documentation that has silently drifted from the model is worse than no
documentation at all, because it is confidently wrong.

So every constant and every calibration figure quoted in the docs is asserted
against the implementation here. If you retune the model, these tests tell you
exactly which sentences need rewriting.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from aurorafox.astronomy import DARKNESS_AT_NAUTICAL
from aurorafox.scoring.aurora import (
    INTENSITY_EXPONENT,
    INTENSITY_FLOOR,
    INTENSITY_REFERENCE_KP,
    OVAL_EDGE_AT_KP0,
    OVAL_EDGE_PER_KP,
    aurora_intensity,
)
from aurorafox.scoring.combine import (
    LONG_RANGE_SCORE_CAP,
    PRIOR_AURORA,
    PRIOR_SKY,
    SCORE_GAMMA,
    to_score,
)
from aurorafox.scoring.sky import (
    CLEAR_THRESHOLD,
    CLUSTER_PERCENTILE,
    CLUSTER_RADIUS_KM,
    MIN_CLUSTER_MEMBERS,
)
from aurorafox.locations import all_cities
from aurorafox.watch import LONG_RANGE_HOURS, MIN_WINDOW_HOURS

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "interpretation"
ALL_MARKDOWN = sorted(DOCS.glob("*.md")) + [ROOT / "CLAUDE.md", ROOT / "README.md"]


def read(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_the_interpretation_folder_exists_with_its_index():
    assert (DOCS / "README.md").is_file()
    for page in ("score-scale.md", "output-schema.md", "reading-results.md",
                 "model-reference.md"):
        assert (DOCS / page).is_file(), page


@pytest.mark.parametrize("path", ALL_MARKDOWN, ids=lambda p: p.name)
def test_internal_markdown_links_resolve(path):
    """A dead link in a doc meant for an LLM is a dead end."""
    for target in re.findall(r"\]\(([^)#][^)]*\.md)\)", path.read_text(encoding="utf-8")):
        assert (path.parent / target).resolve().is_file(), f"{path.name} -> {target}"


def test_index_links_to_every_sibling_page():
    index = read("README.md")
    for page in DOCS.glob("*.md"):
        if page.name != "README.md":
            assert page.name in index, f"{page.name} is not linked from the index"


# ---------------------------------------------------------------------------
# The calibration table in score-scale.md
# ---------------------------------------------------------------------------


def _calibration_rows() -> list[tuple[str, float, float, float, float, float]]:
    rows = []
    for line in read("score-scale.md").splitlines():
        cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not cells[0]:
            continue
        try:
            numbers = [float(c) for c in cells[1:]]
        except ValueError:
            continue
        rows.append((cells[0], *numbers))
    return rows


def test_documented_calibration_table_matches_the_model():
    rows = _calibration_rows()
    assert len(rows) >= 10, f"only parsed {len(rows)} calibration rows"
    for name, aurora, sky, dark, moon, expected in rows:
        assert to_score(aurora * sky * dark * moon) == pytest.approx(expected, abs=0.02), name


def test_documented_kp_score_table_matches_the_model():
    """The `Kp | 0 1 2 3 ...` / `Score | ...` table in score-scale.md."""
    text = read("score-scale.md")
    kp_line = re.search(r"^\| Kp \|(.+)\|$", text, re.M)
    score_line = re.search(r"^\| Score \|(.+)\|$", text, re.M)
    assert kp_line and score_line, "Kp/Score table not found"

    kps = [c.strip().replace("**", "").rstrip("+") for c in kp_line.group(1).split("|")]
    scores = [c.strip().replace("**", "") for c in score_line.group(1).split("|")]
    assert len(kps) == len(scores)

    for kp_text, score_text in zip(kps, scores, strict=True):
        computed = to_score(aurora_intensity(float(kp_text)))
        assert computed == pytest.approx(float(score_text), abs=0.05), kp_text


# ---------------------------------------------------------------------------
# Constants quoted in prose
# ---------------------------------------------------------------------------


def test_quoted_formula_and_constants_are_current():
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in ALL_MARKDOWN)

    assert f"^ {SCORE_GAMMA}" in corpus or f"^{SCORE_GAMMA}" in corpus, "SCORE_GAMMA"
    assert f"{CLUSTER_RADIUS_KM:.0f} km" in corpus, "cluster radius"
    assert f"≥{MIN_CLUSTER_MEMBERS} sites" in corpus or f"≥ {MIN_CLUSTER_MEMBERS} sites" in corpus
    assert f"{CLUSTER_PERCENTILE:.0f}th percentile" in corpus, "cluster percentile"
    assert f"{LONG_RANGE_SCORE_CAP:.1f}" in corpus, "long-range cap"
    assert f"~{LONG_RANGE_HOURS:.0f} h" in corpus, "long-range horizon"
    assert f"≥{MIN_WINDOW_HOURS} consecutive" in corpus or \
           f"≥ {MIN_WINDOW_HOURS} consecutive" in corpus or \
           f"{MIN_WINDOW_HOURS}-consecutive-hour" in corpus, "window rule"
    assert f"aurora {PRIOR_AURORA:.2f}" in corpus and f"sky {PRIOR_SKY:.2f}" in corpus, "priors"
    assert f"{CLEAR_THRESHOLD:.2f}" in corpus, "clear threshold"


def test_quoted_threshold_raw_value_matches_the_model():
    """The docs quote the raw product needed to clear 7.0. Keep it true."""
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in ALL_MARKDOWN)
    required = (6.0 / 9.0) ** (1.0 / SCORE_GAMMA)
    assert f"~{required:.2f}" in corpus, f"threshold raw value should be ~{required:.2f}"


def test_quoted_intensity_curve_matches_the_code():
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in ALL_MARKDOWN)
    expected = (
        f"{INTENSITY_FLOOR:.2f} + {1 - INTENSITY_FLOOR:.2f}·"
        f"(Kp/{INTENSITY_REFERENCE_KP:.0f})^{INTENSITY_EXPONENT}"
    )
    assert expected in corpus, f"intensity curve should be written as {expected!r}"


def test_quoted_oval_relation_matches_the_code():
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in ALL_MARKDOWN)
    assert f"{OVAL_EDGE_AT_KP0} − {OVAL_EDGE_PER_KP:.0f}·Kp" in corpus, "oval edge relation"


def test_quoted_darkness_ladder_matches_the_code():
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in ALL_MARKDOWN)
    assert f"{DARKNESS_AT_NAUTICAL}" in corpus, "nautical darkness value"


#: The registry stores ASCII names; the prose uses proper spelling.
_ACCENTS = str.maketrans({"ø": "o", "í": "i", "á": "a", "é": "e", "å": "a", "ä": "a", "ö": "o"})


def _ascii(text: str) -> str:
    return text.translate(_ACCENTS)


def test_documented_geomagnetic_latitudes_match_the_registry():
    text = _ascii(read("model-reference.md"))
    for city in all_cities():
        pattern = rf"\|\s*{city.name}[^|]*\|[^|]*\|\s*{city.cgm_latitude:.1f}\s*\|"
        assert re.search(pattern, text), f"{city.name} geomagnetic latitude row"


def test_documented_site_count_matches_the_registry():
    total = sum(len(city.points) for city in all_cities())
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in ALL_MARKDOWN)
    assert f"{total} curated" in corpus, f"site count should be {total}"


def test_limiting_factor_values_documented_are_the_ones_emitted():
    """Every string the code can put in `limiting_factor` must be documented."""
    from aurorafox.scoring.combine import HourScore

    source = pathlib.Path(
        HourScore.__module__.replace(".", "/") + ".py"
    )
    body = (ROOT / "src" / source).read_text(encoding="utf-8")
    block = body.split("def limiting_factor")[1].split("\n    def ")[0]
    emitted = set(re.findall(r'return \(?\s*"([^"]+)"', block))
    emitted |= set(re.findall(r'"([a-z][a-z ()\-]+)": ', block))

    documented = read("output-schema.md")
    for value in emitted:
        assert value in documented, f"limiting_factor {value!r} is not documented"
