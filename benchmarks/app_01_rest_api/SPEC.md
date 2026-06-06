# Spec: app_01_rest_api

A FastAPI REST API for managing tasks, backed by SQLite via SQLAlchemy.

---

## Deliverables

One file: `benchmarks/app_01_rest_api/generated/app.py`

Keep it single-file. No sub-packages, no routers split across files.

---

## Required exports from app.py

The test suite imports these directly — they must exist with these exact names:

| Name | Type | Purpose |
|------|------|---------|
| `app` | `FastAPI` instance | The application |
| `get_db` | generator function | SQLAlchemy session dependency |
| `Base` | `DeclarativeBase` | Used by tests to create/drop tables |

---

## Configuration

- Database URL is read from the `DATABASE_URL` environment variable
- Default: `"sqlite:///./tasks.db"`
- Tests will set this to a temp SQLite file before importing — read it at module level

---

## Data model

### Task

| Field | Type | Constraints |
|-------|------|-------------|
| `id` | int | primary key, auto-increment |
| `title` | str | required, max 200 chars, must not be empty |
| `description` | str | optional, default `""` |
| `completed` | bool | default `False` |
| `created_at` | datetime | auto-set to UTC now on creation, never writable by client |

---

## API endpoints

### `GET /tasks`
Returns all tasks.
- **200** — `[Task, ...]` always a list, empty list if no tasks exist

### `POST /tasks`
Creates a new task.
- **Request body:** `{"title": "...", "description": "..."}` (`description` optional)
- **201** — created Task object with all fields populated
- **422** — `title` missing or empty string

### `GET /tasks/{task_id}`
Returns a single task by ID.
- **200** — Task object
- **404** — task does not exist

### `DELETE /tasks/{task_id}`
Deletes a task by ID.
- **204** — no response body
- **404** — task does not exist

---

## Response schema

All task responses must match this exact shape (field names matter — tests check them):

```json
{
  "id": 1,
  "title": "Buy milk",
  "description": "",
  "completed": false,
  "created_at": "2026-06-05T12:00:00"
}
```

---

## Success criteria

```bash
pytest benchmarks/app_01_rest_api/tests/ -v
```

All 13 tests pass, 0 failures, 0 errors.
