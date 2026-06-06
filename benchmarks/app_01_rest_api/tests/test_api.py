"""
Ground truth test suite for app_01_rest_api.

Never generate or modify these tests with AI — they define what correct means.
Run from the repo root: pytest benchmarks/app_01_rest_api/tests/ -v

Expects the implementation at: benchmarks/app_01_rest_api/generated/app.py
Exports required from app.py: app (FastAPI), get_db (dependency), Base (DeclarativeBase)
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Resolve paths relative to this file so pytest can be run from any directory
_APP_DIR = Path(__file__).parent.parent
_GENERATED_DIR = _APP_DIR / "generated"
_TEST_DB = str(_APP_DIR / "test_tasks.db")

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
sys.path.insert(0, str(_GENERATED_DIR))

from app import app, get_db, Base  # noqa: E402

_engine = create_engine(
    f"sqlite:///{_TEST_DB}",
    connect_args={"check_same_thread": False},
)
_TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /tasks
# ---------------------------------------------------------------------------

def test_list_tasks_empty(client):
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_tasks_returns_all(client):
    client.post("/tasks", json={"title": "Task A"})
    client.post("/tasks", json={"title": "Task B"})
    resp = client.get("/tasks")
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert "Task A" in titles
    assert "Task B" in titles
    assert len(resp.json()) == 2


# ---------------------------------------------------------------------------
# POST /tasks
# ---------------------------------------------------------------------------

def test_create_task_minimal(client):
    resp = client.post("/tasks", json={"title": "Buy milk"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Buy milk"
    assert body["description"] == ""
    assert body["completed"] is False
    assert "id" in body
    assert "created_at" in body


def test_create_task_with_description(client):
    resp = client.post("/tasks", json={"title": "Buy milk", "description": "Whole milk"})
    assert resp.status_code == 201
    assert resp.json()["description"] == "Whole milk"


def test_create_task_missing_title(client):
    resp = client.post("/tasks", json={"description": "No title here"})
    assert resp.status_code == 422


def test_create_task_empty_title(client):
    resp = client.post("/tasks", json={"title": ""})
    assert resp.status_code == 422


def test_create_task_returns_unique_ids(client):
    id1 = client.post("/tasks", json={"title": "First"}).json()["id"]
    id2 = client.post("/tasks", json={"title": "Second"}).json()["id"]
    assert id1 != id2


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}
# ---------------------------------------------------------------------------

def test_get_task_exists(client):
    created = client.post("/tasks", json={"title": "Get me"}).json()
    resp = client.get(f"/tasks/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
    assert resp.json()["title"] == "Get me"


def test_get_task_not_found(client):
    resp = client.get("/tasks/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /tasks/{task_id}
# ---------------------------------------------------------------------------

def test_delete_task_exists(client):
    created = client.post("/tasks", json={"title": "Delete me"}).json()
    resp = client.delete(f"/tasks/{created['id']}")
    assert resp.status_code == 204


def test_delete_task_removes_it(client):
    created = client.post("/tasks", json={"title": "Gone soon"}).json()
    client.delete(f"/tasks/{created['id']}")
    resp = client.get(f"/tasks/{created['id']}")
    assert resp.status_code == 404


def test_delete_task_not_found(client):
    resp = client.delete("/tasks/99999")
    assert resp.status_code == 404


def test_delete_does_not_affect_other_tasks(client):
    a = client.post("/tasks", json={"title": "Keep me"}).json()
    b = client.post("/tasks", json={"title": "Delete me"}).json()
    client.delete(f"/tasks/{b['id']}")
    resp = client.get(f"/tasks/{a['id']}")
    assert resp.status_code == 200
