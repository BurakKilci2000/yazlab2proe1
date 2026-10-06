import sys
from pathlib import Path

import mongomock
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    client = mongomock.MongoClient(tz_aware=True)
    database = client["test_kocaeli_haber"]
    from db.mongo import init_indexes
    init_indexes(database)
    return database


@pytest.fixture
def fixture_html():
    def _read(name):
        return (FIXTURES / name).read_text(encoding="utf-8")
    return _read
