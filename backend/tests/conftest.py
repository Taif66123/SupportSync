import os
import tempfile

# Must be set before any app import — settings are read at import time.
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only-0123456789abcdef")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.modules.auth.models  # noqa: F401,E402
import app.modules.chat.models  # noqa: F401,E402
import app.modules.tickets.models  # noqa: F401,E402
import app.modules.users.models  # noqa: F401,E402
from app.core.database import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.users import service as users_service  # noqa: E402
from app.modules.users.models import Role  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session")
def engine():
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        engine = create_engine(test_url, pool_pre_ping=True)
    else:
        tmpdir = tempfile.mkdtemp(prefix="supportsflow-tests-")
        engine = create_engine(
            f"sqlite:///{tmpdir}/test.db", connect_args={"check_same_thread": False}
        )
        # The pysqlite driver cannot emit SAVEPOINT unless it runs in SQLAlchemy's
        # documented "serializable / savepoint" recipe (isolation_level=None plus an
        # explicit BEGIN event hook). Without it, the rolled-back-transaction harness
        # below degrades silently: any commit made mid-test (e.g. the WS chat handler's
        # per-frame commit) persists for the rest of the run and poisons later tests.
        @event.listens_for(engine, "connect")
        def _sqlite_raw_isolation(dbapi_connection, _connection_record):
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _sqlite_explicit_begin(connection):
            connection.exec_driver_sql("BEGIN")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    """A session scoped to one rolled-back transaction per test — tests never see
    each other's data, and API requests share the test's session via the override below.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(session):
    app = create_app()

    def override():
        yield session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str, password: str = "passw0rd!", full_name: str = "Test User") -> dict:
    response = client.post(f"{API}/auth/register", json={"email": email, "password": password, "full_name": full_name})
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str) -> dict:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def headers(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def admin_tokens(client, session):
    users_service.create_staff(
        session, email="admin@test.io", password="adminpass1", full_name="Admin", role=Role.ADMIN
    )
    return login(client, "admin@test.io", "adminpass1")


@pytest.fixture
def agent_tokens(client, session, admin_tokens):
    users_service.create_staff(
        session, email="agent@test.io", password="agentpass1", full_name="Agent", role=Role.AGENT
    )
    return login(client, "agent@test.io", "agentpass1")


@pytest.fixture
def customer_tokens(client):
    return register(client, "customer@test.io", full_name="Customer")


@pytest.fixture
def customer2_tokens(client):
    return register(client, "customer2@test.io", full_name="Customer Two")
