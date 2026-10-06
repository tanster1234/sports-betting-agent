"""Build the WNBA Betting Lab page with fresh playoff-tracker data.

usage: python3 scripts/build_lab_page.py [--tracker tracker.json] [--out site/dist/wnba-betting-lab.html]

Without --tracker it runs scripts/playoff_tracker.py first (needs site.api.espn.com for the
upcoming-games section). Publish the output file as the artifact page.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "site" / "wnba-betting-lab.html"
PLACEHOLDER = "/*TRACKER_JSON*/null"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tracker")
    ap.add_argument("--out", default=str(ROOT / "site" / "dist" / "wnba-betting-lab.html"))
    a = ap.parse_args()
    if a.tracker:
        data = json.loads(Path(a.tracker).read_text())
    else:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "tracker.json"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "playoff_tracker.py"), "--out", str(out)], check=True)
            data = json.loads(out.read_text())
    html = TEMPLATE.read_text()
    if PLACEHOLDER not in html:
        sys.exit(f"placeholder {PLACEHOLDER!r} not found in {TEMPLATE}")
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")   # safe inside <script>
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(html.replace(PLACEHOLDER, blob))
    print(f"wrote {a.out} (tracker: {data['summary']}, results through {data['data_through']})")


if __name__ == "__main__":
    main()
