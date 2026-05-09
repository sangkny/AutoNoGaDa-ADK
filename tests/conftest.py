"""pytest — ASGI 클라이언트 (FastAPI Test)."""
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from database import engine
from main import app


@pytest_asyncio.fixture(autouse=True)
async def _dispose_async_engine_after_test() -> AsyncIterator[None]:
    """pytest-asyncio 마다 새 이벤트 루프가 되면 기존 asyncpg 커넥션과 충돌하므로 풀을 비운다."""
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
