# Architecture — MCP Fadr Server

> Version: 0.1.0

---

## Overview

The MCP Fadr Server is a stateless, single-process Python application that bridges the
Model Context Protocol (MCP) and the Fadr audio-analysis API. LLMs interact with structured
tools; the server translates tool calls into Fadr API workflows and returns normalized,
schema-validated JSON responses.

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP CLIENT (LLM host)                    │
│                   (Claude Desktop, Claude Code, etc.)           │
└────────────────────────────┬────────────────────────────────────┘
                             │ MCP protocol (JSON-RPC over stdio)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  TRANSPORT LAYER   server/transport/                            │
│  • mcp_server.py   — MCP server initialization, tool registry  │
│  • Deserializes tool call params, calls Tools layer             │
│  • Serializes envelope response back to MCP client              │
└────────────────────────────┬────────────────────────────────────┘
                             │ Python function call (typed dict)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  TOOLS LAYER       server/tools/                                │
│  • separate_stems.py  extract_midi.py  analyze_music.py        │
│  • Validates input against Pydantic schemas                     │
│  • Calls Service layer                                          │
│  • Wraps result/exception in standard response envelope         │
│  • No business logic; no HTTP calls                             │
└────────────────────────────┬────────────────────────────────────┘
                             │ Python function call (Pydantic models)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  SERVICE LAYER     server/services/                             │
│  • stem_service.py — orchestrates full Fadr pipeline            │
│  • Translates Fadr raw responses → normalized output models     │
│  • Handles polling loop (5-second interval, configurable)       │
│  • Raises typed exceptions (FadrClientError, TaskTimeoutError)  │
│  • No transport or MCP awareness                                │
└────────────────────────────┬────────────────────────────────────┘
                             │ Python function call (Pydantic models)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  CLIENT LAYER      server/clients/                              │
│  • fadr_client.py — all HTTP calls to https://api.fadr.com     │
│  • Methods: upload_audio(), create_asset(), create_stem_task()  │
│             poll_task(), get_download_url()                     │
│  • Centralizes auth (Bearer token), timeout, retries            │
│  • Raises FadrClientError with structured detail on HTTP errors │
│  • Protocol: abstract base FadrClientBase (enables mocking)     │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  SCHEMA LAYER      server/schemas/                              │
│  • Pydantic v2 models for all inputs, outputs, Fadr responses   │
│  • JSON Schema export (used in tool registration)               │
│  • Single source of truth for data shapes                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
mcp-fadr-server/
│
├── server/
│   ├── main.py                  # Entrypoint: creates and runs the MCP server
│   │
│   ├── transport/
│   │   └── mcp_server.py        # MCP initialization, tool registration handler
│   │
│   ├── tools/
│   │   ├── separate_stems.py    # Tool handler: validate → call service → wrap
│   │   ├── extract_midi.py      # Tool handler: validate → call service → wrap
│   │   └── analyze_music.py     # Tool handler: validate → call service → wrap
│   │
│   ├── services/
│   │   └── stem_service.py      # Full Fadr pipeline orchestration + normalization
│   │
│   ├── clients/
│   │   ├── base.py              # Abstract base class FadrClientBase
│   │   ├── fadr_client.py       # Real HTTP implementation (httpx)
│   │   └── mock_client.py       # In-memory mock for testing
│   │
│   ├── schemas/
│   │   ├── inputs.py            # Pydantic input models for all tools
│   │   ├── outputs.py           # Pydantic output models (stems, midi, analysis)
│   │   ├── envelope.py          # SuccessResponse / ErrorResponse envelope
│   │   └── fadr_responses.py    # Pydantic models for raw Fadr API responses
│   │
│   └── utils/
│       ├── logging.py           # Structured JSON logger factory
│       ├── url_validator.py     # URL allowlist/denylist validation
│       └── config.py            # Settings via pydantic-settings (ENV vars)
│
├── tests/
│   ├── unit/
│   │   ├── test_schemas.py      # Schema validation tests
│   │   ├── test_stem_service.py # Service layer tests (mock client)
│   │   └── test_client_errors.py# Client error mapping tests
│   └── golden/
│       └── test_golden_outputs.py # Compare outputs to examples/
│
├── docs/
│   ├── api_contract.md          # Tool schemas + response examples (authoritative)
│   ├── architecture.md          # This file
│   ├── security.md              # Key handling, logging rules, URL validation
│   └── development.md           # How to run tests, lint, format, typecheck
│
├── examples/
│   ├── example_requests.json    # Sample tool inputs
│   └── example_responses.json   # Expected tool outputs
│
├── .github/
│   └── workflows/
│       └── ci.yml               # Lint → typecheck → test → coverage
│
├── pyproject.toml               # Build config, deps, tool settings, entrypoint
├── README.md                    # Project overview + quickstart
├── LICENSE                      # MIT
├── .env.example                 # ENV var documentation (no secrets)
└── .gitignore
```

---

## Data Flow: `separate_stems` Example

```
1.  MCP Client sends:
      tool="separate_stems"
      params={"audio_url": "https://example.com/song.mp3", "quality": "hqPreview"}

2.  Transport: deserializes params, calls tools.separate_stems.handle(params)

3.  Tool: validates with SeparateStemsInput Pydantic model
          calls stem_service.separate_stems(audio_url, quality)

4.  Service:
    a. URL-validates audio_url (https scheme only, no private IPs)
    b. Downloads audio bytes from audio_url (httpx, timeout=30s)
    c. Calls fadr_client.get_upload_url(name, extension)
       → POST /assets/upload2 → returns {url, s3Path}
    d. Calls fadr_client.upload_audio(presigned_url, audio_bytes, mime_type)
       → PUT <presigned_url> with Content-Type header
    e. Calls fadr_client.create_asset(name, extension, s3Path)
       → POST /assets → returns {_id, ...}
    f. Calls fadr_client.create_stem_task(asset_id, model="main")
       → POST /assets/analyze/stem → returns {_id: task_id, ...}
    g. Polls fadr_client.get_task(task_id) every 5s until stems ready
       → GET /tasks/:_id → monitors task.asset.stems[]
    h. For each stem asset _id, calls fadr_client.get_download_url(id, quality)
       → GET /assets/download/:id/:quality → returns {url}
    i. Returns StemsResult(job_id, processing_time_ms, stems=[...])

5.  Tool: wraps in SuccessResponse envelope

6.  Transport: serializes to JSON, returns to MCP client
```

---

## Key Design Decisions

### 1. Single Fadr Task for All Tools
All three MCP tools invoke the same Fadr `POST /assets/analyze/stem` with `model="main"`.
Each tool returns a different projection of the task result. No caching in MVP 0.1.0.

### 2. Async Polling in Synchronous Tool Call
The MCP tool call blocks until the Fadr task completes (or times out). Polling runs in
an `asyncio` loop with configurable interval (default 5s) and timeout (default 300s).
The server uses `asyncio` throughout; the MCP library handles the event loop.

### 3. Mockable Client via Abstract Base
`FadrClientBase` (ABC) is injected into services. Tests use `MockFadrClient`.
The real client is wired in `main.py` via the settings object.

### 4. URL Handling: Download-then-Upload
`audio_url` inputs are external URLs. The server downloads the audio and re-uploads
to Fadr via presigned URL. This is the only way to feed audio to the Fadr API.
URL validation (SSRF prevention) is applied before any HTTP request is made.

### 5. Structured Logging Only
All log records are JSON objects. No free-text log lines that might interpolate
sensitive data. API keys are never included in log fields.

---

## Dependency Graph (no circular imports rule)

```
transport  →  tools  →  services  →  clients
                    ↘              ↗
                      schemas
                    ↘
                      utils
```

`utils` and `schemas` have no internal cross-dependencies.
`clients` depends only on `schemas` (for request/response models) and `utils` (logging, config).

---

## Configuration (ENV vars)

See `.env.example` for the full list. Key settings:

| ENV var | Default | Description |
|---|---|---|
| `FADR_API_KEY` | — (required) | Fadr API bearer token |
| `FADR_BASE_URL` | `https://api.fadr.com` | Fadr API base URL |
| `FADR_TIMEOUT_S` | `30` | HTTP request timeout (seconds) |
| `FADR_POLL_INTERVAL_S` | `5` | Task polling interval (seconds) |
| `FADR_POLL_TIMEOUT_S` | `300` | Max time to wait for task completion |
| `FADR_MAX_RETRIES` | `3` | HTTP retry count on transient errors |
| `LOG_LEVEL` | `INFO` | Python log level |
| `ALLOWED_AUDIO_SCHEMES` | `https` | Comma-separated URL schemes allowed for audio_url |
| `MAX_AUDIO_SIZE_MB` | `100` | Max downloadable audio file size |
