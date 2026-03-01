# Development Guide — MCP Fadr Server

> Version: 0.1.0

---

## Prerequisites

- Python 3.11 or later
- `pip` (bundled with Python) or `pipx`
- A Fadr account with API access (Fadr Plus subscription)
- Git

---

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/<your-org>/mcp-fadr-server.git
cd mcp-fadr-server
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

### 3. Install in editable mode with all dev dependencies

```bash
pip install -e ".[dev]"
```

This installs:
- Runtime: `mcp`, `httpx`, `pydantic`, `pydantic-settings`, `python-dotenv`
- Dev: `pytest`, `pytest-cov`, `pytest-asyncio`, `ruff`, `mypy`, `black`

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env and set FADR_API_KEY=<your-key>
```

The server loads `.env` automatically in non-CI environments via `python-dotenv`.

---

## Running the Server

```bash
mcp-fadr          # runs server/main.py via the console_script entrypoint
# or directly:
python -m server.main
```

The server communicates over stdio and is designed to be launched by an MCP host
(e.g. Claude Desktop). It does not open a network port.

### Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fadr": {
      "command": "mcp-fadr",
      "env": {
        "FADR_API_KEY": "<your-key>"
      }
    }
  }
}
```

---

## Running Tests

### All tests

```bash
pytest
```

### With coverage report

```bash
pytest --cov=server --cov-report=term-missing --cov-fail-under=80
```

Coverage is enforced at ≥ 80% on `server/services/` and `server/clients/`.

### Specific test file

```bash
pytest tests/unit/test_stem_service.py -v
```

### Async tests

Tests use `pytest-asyncio`. Mark async test functions with `@pytest.mark.asyncio`.
The `asyncio_mode = "auto"` setting in `pyproject.toml` applies it project-wide.

### Golden output tests

```bash
pytest tests/golden/ -v
```

Golden tests compare tool outputs against `examples/example_responses.json` using
the mock client. They are deterministic and require no network access.

---

## Linting

```bash
ruff check .
```

Configuration is in `pyproject.toml` under `[tool.ruff]`.
Ruff replaces flake8, isort, and pyupgrade in one tool.

Fix auto-fixable issues:

```bash
ruff check . --fix
```

---

## Formatting

```bash
black .
# or check only (no changes):
black . --check
```

Ruff format is also available as an alternative:
```bash
ruff format .
```

---

## Type Checking

```bash
mypy server/
```

Configuration is in `pyproject.toml` under `[tool.mypy]`.
Strict mode is enabled. All public functions must have type annotations.

---

## Pre-commit Hooks

Install hooks (runs automatically on `git commit`):

```bash
pip install pre-commit
pre-commit install
```

Hooks run:
1. `ruff check` (lint)
2. `black --check` (format)
3. `mypy` (typecheck)

To run hooks manually on all files:

```bash
pre-commit run --all-files
```

---

## CI Pipeline

GitHub Actions runs on every push and pull request:

1. **Install** — `pip install -e ".[dev]"`
2. **Lint** — `ruff check .`
3. **Format check** — `black . --check`
4. **Typecheck** — `mypy server/`
5. **Tests + coverage** — `pytest --cov=server --cov-fail-under=80`

All steps run without network access to Fadr (tests use the mock client).

See `.github/workflows/ci.yml` for the full workflow definition.

---

## Project Layout Quick Reference

```
server/clients/mock_client.py   ← use this in tests, not the real client
server/schemas/                 ← all Pydantic models live here
tests/unit/                     ← pure unit tests, no network
tests/golden/                   ← compare output to examples/
examples/                       ← golden reference files
```

---

## Adding a New Tool (future)

> Not in MVP scope. Document here when a new tool is added.

1. Define input/output schemas in `server/schemas/inputs.py` and `outputs.py`
2. Add the tool handler in `server/tools/<name>.py`
3. Register the tool in `server/transport/mcp_server.py`
4. Add service logic in `server/services/` (or extend `stem_service.py`)
5. Update `docs/api_contract.md` with the new tool schema
6. Add example request/response to `examples/`
7. Add tests in `tests/unit/`

---

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`) is used.
The version is declared once in `pyproject.toml` under `[project] version`.
Do not maintain a separate `VERSION` file.

MVP release: `0.1.0`
