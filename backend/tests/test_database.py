import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.database import get_db_session
from app.main import app


def test_settings_load_default_database_url() -> None:
    settings = Settings()

    assert str(settings.database_url).startswith("postgresql+asyncpg://")


@pytest.mark.anyio
async def test_database_session_dependency_rolls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        committed = False
        rolled_back = False

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            self.committed = True

        async def rollback(self) -> None:
            self.rolled_back = True

    fake_session = FakeSession()

    def fake_session_factory() -> FakeSession:
        return fake_session

    monkeypatch.setattr("app.core.database.AsyncSessionLocal", fake_session_factory)

    session_iterator = get_db_session()
    session = await anext(session_iterator)

    assert session is fake_session

    with pytest.raises(RuntimeError):
        await session_iterator.athrow(RuntimeError("boom"))

    assert fake_session.rolled_back is True
    assert fake_session.committed is False


@pytest.mark.anyio
async def test_database_health_check_uses_connection_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_check_database_connection() -> bool:
        return True

    monkeypatch.setattr(
        "app.api.v1.routes.health.check_database_connection",
        fake_check_database_connection,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_database_health_check_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_check_database_connection() -> bool:
        raise OperationalError("SELECT 1", {}, Exception("offline"))

    monkeypatch.setattr(
        "app.api.v1.routes.health.check_database_connection",
        fake_check_database_connection,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health/database")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
