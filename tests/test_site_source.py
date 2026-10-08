"""The live site must only ever show real data.

Forecasts, model values, "Logged" times and prices come from site/data (built from forecasts/*.csv,
config/kickoffs.json and the data branch). These tests fail if the site source, or the build job,
contains demo or sample code: switches that inject values, URL parameters that change what is
shown, hard-coded model values, or a clock override. design mockups (mockups/, not shipped) may
use such switches; the site may not.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
SHIPPED = {".html", ".js", ".css", ".svg"}

BANNED_WORDS = re.compile(
    r"\b(demo|sample|samples|mock|mocks|mocked|mockup|fake|dummy|lorem|placeholder|fixture)\b", re.IGNORECASE
)
# (pattern, why)
BANNED_CODE = [
    (re.compile(r"\bp_home\s*[:=]\s*-?\d"), "hard-coded model probability"),
    (re.compile(r"\.model\s*=[^=]"), "assigns a model onto a game in the browser"),
    (re.compile(r"\bmodel\s*:\s*\{"), "builds a model object in the browser"),
    (re.compile(r"\blogged\s*[:=]\s*true\b"), "forces a game to look logged"),
    (re.compile(r"Math\.random"), "random values"),
    (re.compile(r"""get\(\s*["'](?!theme["'])\w+["']\s*\)"""), "URL parameter other than theme"),
    (re.compile(r"\blocation\.hash\b|\blocation\.search\b(?!\))"), "reads the URL to change content"),
]


def shipped_files(root: Path) -> list[Path]:
    out = [p for p in (root / "site").rglob("*") if p.suffix in SHIPPED and "data" not in p.relative_to(root / "site").parts]
    job = root / "jobs" / "build_site.py"
    return out + ([job] if job.exists() else [])


def find_violations(root: Path) -> list[str]:
    found = []
    for path in shipped_files(root):
        text = path.read_text()
        for n, line in enumerate(text.splitlines(), 1):
            where = f"{path.relative_to(root)}:{n}"
            if m := BANNED_WORDS.search(line):
                found.append(f"{where}: word {m.group(0)!r}: {line.strip()[:90]}")
            if path.suffix == ".py":  # the build job: banned words only (dict .get() is normal Python)
                continue
            for pattern, why in BANNED_CODE:
                if pattern.search(line):
                    found.append(f"{where}: {why}: {line.strip()[:90]}")
    return found


def test_site_has_pages_and_scripts_to_scan():
    names = {p.name for p in shipped_files(ROOT)}
    assert {"index.html", "log.html", "week.html", "method.html", "site.js", "strip.js", "site.css", "build_site.py"} <= names


def test_site_source_has_no_demo_or_sample_code():
    assert find_violations(ROOT) == []


def test_the_scan_catches_what_it_is_meant_to(tmp_path):
    """A scan that finds nothing proves nothing: seed a fake site with each kind of offence."""
    (tmp_path / "site" / "assets").mkdir(parents=True)
    (tmp_path / "site" / "data").mkdir()
    (tmp_path / "site" / "data" / "games.json").write_text('{"demo": true}')  # generated data is skipped
    (tmp_path / "site" / "index.html").write_text("<p>clean</p>")
    bad = {
        "a.js": 'var q = new URLSearchParams(location.search).get("demo");',
        "b.js": 'g.model = { name: "x", p_home: 71.3 };',
        "c.js": "var sample = 1;",
        "d.js": 'var now = Number(p.get("now"));',
        "e.js": "game.logged = true;",
        "f.css": "/* mock values */",
    }
    for name, text in bad.items():
        (tmp_path / "site" / "assets" / name).write_text(text)
    flagged = "\n".join(find_violations(tmp_path))
    for name in bad:
        assert name in flagged, f"{name} was not flagged"
    assert "games.json" not in flagged
    assert "index.html" not in flagged


def test_the_only_url_parameter_the_site_reads_is_the_theme():
    keys = set()
    for path in shipped_files(ROOT):
        if path.suffix in {".js", ".html"}:
            keys |= set(re.findall(r"""\.get\(\s*["'](\w+)["']\s*\)""", path.read_text()))
    assert keys <= {"theme"}
