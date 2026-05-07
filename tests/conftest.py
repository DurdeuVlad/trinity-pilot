import pytest
from trinity_pilot.memory.db import open_db


@pytest.fixture
def in_memory_db():
    conn = open_db(":memory:")
    yield conn
    conn.close()
