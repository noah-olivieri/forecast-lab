"""The site's browser JS (site/assets/*.js) run under Node, in several time zones.

Age and timestamp helpers must depend only on UTC instants and real milliseconds, never on the
machine's zone; every displayed time is Pacific on purpose. Skipped if Node is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
ASSETS = Path(__file__).parent.parent / "site" / "assets"
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

HARNESS = """
const fs = require("fs"), vm = require("vm");
global.window = global;
global.document = { addEventListener() {}, getElementById() { return null; }, documentElement: { dataset: {} } };
global.addEventListener = () => {};
for (const f of ["site.js", "strip.js"]) vm.runInThisContext(fs.readFileSync(process.argv[2] + "/" + f, "utf8"));
const input = JSON.parse(process.argv[3]);
const Lab = global.Lab, T = (s) => Date.parse(s);
const out = {};
out.ago = input.ago.map(([a, b]) => Lab.ago(T(a), T(b)));
out.line = input.line.map(([snaps, now]) => Lab.snapshotLine(snaps, T(now)));
out.lock = input.lock.map(([g, now]) => Lab.lockState(g, T(now)));
out.cross = input.cross.map(([c]) => Lab.crossNote(c, { home: "Dallas" }));
console.log(JSON.stringify(out));
"""

SNAP = "2026-10-07T17:18:20Z"  # Wed 10:18 AM PT
CASES = {
    "ago": [
        [SNAP, "2026-10-07T17:38:20Z"],
        [SNAP, "2026-10-07T19:03:37Z"],  # Wed 12:03 PM PT, the moment this was checked
        [SNAP, "2026-10-09T01:00:00Z"],  # Thu 6 PM PT
        [SNAP, "2026-10-10T17:18:20Z"],
    ],
    "line": [
        [{"kalshi": SNAP, "polymarket_us": SNAP}, "2026-10-07T19:03:37Z"],
        [{"kalshi": SNAP, "polymarket_us": SNAP}, "2026-10-09T01:00:00Z"],
        [{"kalshi": SNAP, "polymarket_us": "2026-10-07T15:00:00Z"}, "2026-10-07T19:03:37Z"],
        [{}, "2026-10-07T19:03:37Z"],
    ],
    "lock": [
        [{"logged": False, "lock_utc": "2026-10-08T00:15:00Z"}, "2026-10-07T23:00:00Z"],
        [{"logged": False, "lock_utc": "2026-10-08T00:15:00Z"}, "2026-10-08T01:00:00Z"],
        [{"logged": True, "lock_utc": "2026-10-08T00:15:00Z"}, "2026-10-08T01:00:00Z"],
    ],
    "cross": [
        [{"buy": "polymarket_us", "buy_price": 59.5, "sell": "kalshi", "sell_price": 60, "gross": 0.5,
          "kalshi_fee": 1.68, "net": -1.18, "survives": False}],
        [{"buy": "kalshi", "buy_price": 42, "sell": "polymarket_us", "sell_price": 44, "gross": 2,
          "kalshi_fee": 1.7052, "net": 0.2948, "survives": True}],
        [{"buy": "kalshi", "buy_price": 42, "sell": "polymarket_us", "sell_price": 44, "gross": 2,
          "kalshi_fee": None, "net": None, "survives": None}],
        [None],
    ],
}


def run_js(tz: str, tmp_path: Path) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(HARNESS)
    r = subprocess.run(
        [NODE, str(script), str(ASSETS), json.dumps(CASES)],
        capture_output=True, text=True, env={"TZ": tz, "PATH": "/usr/bin:/bin"}, check=True,
    )  # fmt: skip
    return json.loads(r.stdout)


@pytest.mark.parametrize("tz", ["UTC", "America/Los_Angeles", "Asia/Tokyo", "Pacific/Kiritimati"])
def test_ages_and_stamps_do_not_depend_on_the_machine_zone(tz, tmp_path):
    out = run_js(tz, tmp_path)
    assert out["ago"] == ["20 min", "2 h", "32 h", "3 days"]
    fresh, stale, mixed, none = out["line"]
    assert "Market prices as of" in fresh and "Wed 10/7, 10:18 AM PT" in fresh
    assert "stale" not in fresh  # 1.75 h old at Wed 12:03 PM PT
    assert "Wed 10/7, 10:18 AM PT" in stale and "That is 32 h old" in stale
    assert "Kalshi as of" in mixed and "Wed 10/7, 8:00 AM PT" in mixed
    assert "That is 4 h old" in mixed  # judged on the older venue
    assert none == "No market snapshot was available when the site was built."


def test_lock_state_uses_the_clock_it_is_given(tmp_path):
    assert run_js("UTC", tmp_path)["lock"] == ["locks", "missed", "logged"]


def test_cross_note_wording(tmp_path):
    no, yes, nofee, absent = run_js("UTC", tmp_path)["cross"]
    assert "Cross-venue gap" in no and "0.5¢ gross" in no
    assert "buy Dallas on Polymarket at 59.5¢, sell it on Kalshi at 60¢" in no
    assert "After est. fees (Kalshi 1.7¢): −1.2¢, so it doesn't survive" in no
    assert "Paper only" in no
    assert "After est. fees (Kalshi 1.7¢): +0.3¢" in yes and "Polymarket US's fee isn't counted" in yes
    assert "no net figure" in nofee
    assert absent == ""
