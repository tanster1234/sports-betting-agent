import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixture_json():
    def load(name):
        with open(FIXTURES / name) as f:
            return json.load(f)
    return load


@pytest.fixture(scope="session")
def wnba_games():
    from betlab import wnba
    return wnba.load_games()


@pytest.fixture(scope="session")
def wnba_lines():
    from betlab import wnba
    return wnba.load_lines()


# calibration.md and the golden-number tests describe the snapshot of games before this date;
# refreshed data only appends newer games, so those tests keep using this window.
CALIBRATION_CUTOFF = "2026-10-02"


@pytest.fixture(scope="session")
def calib_games(wnba_games):
    return [g for g in wnba_games if g["date"] < CALIBRATION_CUTOFF]


@pytest.fixture(scope="session")
def calib_lines(wnba_lines):
    return [r for r in wnba_lines if r["date"] < CALIBRATION_CUTOFF]


@pytest.fixture(scope="session")
def wnba_model(calib_games):
    from betlab import wnba
    return wnba.fit_model(calib_games)
