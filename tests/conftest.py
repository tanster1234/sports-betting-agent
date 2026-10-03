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


@pytest.fixture(scope="session")
def wnba_model(wnba_games):
    from betlab import wnba
    return wnba.fit_model(wnba_games)
