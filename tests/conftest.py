from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.main import app
from app.models import Person


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def ensure_seed():
    """Seed DB once per test session if it's empty."""
    async with AsyncSessionLocal() as s:
        count = (await s.execute(select(func.count(Person.person_id)))).scalar_one()
    if count == 0:
        import subprocess, sys
        subprocess.check_call([sys.executable, "/code/scripts/seed_from_sample.py"])


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
