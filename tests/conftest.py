"""Shared pytest fixtures for all tests."""
import pytest
import os

@pytest.fixture(scope="session")
def database_url():
    """Get database URL from environment, defaulting to robomonkey database."""
    return os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/robomonkey")
