# mcp-fadr-server

[![CI](https://github.com/ebuart/mcp-fadr-server/actions/workflows/ci.yml/badge.svg)](https://github.com/ebuart/mcp-fadr-server/actions/workflows/ci.yml)

An MCP (Model Context Protocol) server that integrates the [Fadr API](https://fadr.com/docs/api),
enabling LLMs to separate audio stems, extract MIDI, and analyze chord progressions, key,
and tempo from audio files — all via natural language tool calls.

---

## Features

- **Stem separation** — split any audio track into vocals, bass, drums, melodies, and instrumental
- **MIDI extraction** — get MIDI files for each stem and the full chord progression
- **Music analysis** — detect key, tempo (BPM), time signature, and chord progression
- **Structured outputs** — every tool response is a strictly-typed JSON envelope; no free-text
- **Secure by default** — SSRF-safe URL validation, secrets never logged, HTTPS-only
- **Async polling** — handles Fadr's async task lifecycle transparently
- **Fully typed** — Python 3.11+, Pydantic v2, mypy strict mode
- **Testable** — mockable Fadr client, ≥ 80% test coverage enforced in CI

---

## Architecture Overview

```
MCP Client (LLM host)
       │ JSON-RPC / stdio
       ▼
  Transport Layer     ← MCP protocol handling, tool registration
       │
       ▼
   Tools Layer        ← Input validation, response envelope wrapping
       │
       ▼
  Service Layer       ← Fadr pipeline orchestration, output normalization
       │
       ▼
   Client Layer       ← All HTTP calls to api.fadr.com (mockable)
       │
       ▼
  Schema Layer        ← Pydantic v2 models, JSON Schema export
```

See [docs/architecture.md](docs/architecture.md) for the full layer diagram and design decisions.

---

## Quickstart

### 1. Install

```bash
git clone https://github.com/ebuart/mcp-fadr-server.git
cd mcp-fadr-server

python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
# Set your Fadr API key:
echo "FADR_API_KEY=your_key_here" >> .env
```

### 3. Run

```bash
mcp-fadr
```

The server listens on stdio and is designed to be launched by an MCP host.

### 4. Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fadr": {
      "command": "mcp-fadr",
      "env": {
        "FADR_API_KEY": "your_key_here"
      }
    }
  }
}
```

Restart Claude Desktop. You can now ask Claude to separate stems, extract MIDI, or analyze music.

---

## Example Tool Calls

### Separate stems

```json
{
  "tool": "separate_stems",
  "params": {
    "audio_url": "https://example.com/my-song.mp3",
    "quality": "hqPreview"
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "job_id": "64f1a2b3c4d5e6f7a8b9c0d1",
    "processing_time_ms": 18420,
    "stems": [
      { "name": "vocals",       "url": "https://..." },
      { "name": "bass",         "url": "https://..." },
      { "name": "drums",        "url": "https://..." },
      { "name": "melodies",     "url": "https://..." },
      { "name": "instrumental", "url": "https://..." }
    ]
  },
  "error": null
}
```

### Extract MIDI

```json
{
  "tool": "extract_midi",
  "params": {
    "audio_url": "https://example.com/my-song.mp3"
  }
}
```

### Analyze music

```json
{
  "tool": "analyze_music",
  "params": {
    "audio_url": "https://example.com/my-song.mp3"
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "job_id": "64f1a2b3c4d5e6f7a8b9c0d3",
    "processing_time_ms": 19850,
    "key": "A minor",
    "tempo_bpm": 128.0,
    "time_signature": "4/4",
    "chord_progression": [
      { "chord": "Am", "start_beat": 1, "duration_beats": 4 },
      { "chord": "F",  "start_beat": 5, "duration_beats": 4 }
    ]
  },
  "error": null
}
```

Full schema documentation: [docs/api_contract.md](docs/api_contract.md)

---

## Configuration

| ENV Variable | Required | Default | Description |
|---|---|---|---|
| `FADR_API_KEY` | **Yes** | — | Fadr API bearer token |
| `FADR_BASE_URL` | No | `https://api.fadr.com` | Fadr API base URL |
| `FADR_TIMEOUT_S` | No | `30` | HTTP request timeout (seconds) |
| `FADR_POLL_INTERVAL_S` | No | `5` | Task polling interval (seconds) |
| `FADR_POLL_TIMEOUT_S` | No | `300` | Max task wait time (seconds) |
| `FADR_MAX_RETRIES` | No | `3` | Retry count on transient HTTP errors |
| `LOG_LEVEL` | No | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `ALLOWED_AUDIO_SCHEMES` | No | `https` | Comma-separated allowed URL schemes |
| `MAX_AUDIO_SIZE_MB` | No | `100` | Max audio download size in MB |

See [docs/security.md](docs/security.md) for security guidance on each variable.

---

## Requirements

- Python 3.11+
- Fadr Plus subscription ($10/month) — required for API access
- Fadr charges $0.05 per minute of audio processed

---

## Development

```bash
pip install -e ".[dev]"
pytest --cov=server --cov-fail-under=80
ruff check .
mypy server/
```

Full guide: [docs/development.md](docs/development.md)

---

## Troubleshooting

### Server not appearing in Claude Desktop

1. Verify `mcp-fadr` is on your `PATH`: `which mcp-fadr`
2. Check the `FADR_API_KEY` is set in the Claude Desktop config env block
3. Restart Claude Desktop after config changes
4. Check MCP server logs: Claude Desktop writes them to `~/Library/Logs/Claude/`

### `INVALID_URL` error

- Ensure the audio URL uses `https://` (not `http://`)
- Ensure the URL is publicly accessible (no authentication required)
- Check the file extension is a supported audio format: `mp3`, `wav`, `aac`, `flac`, `ogg`, `m4a`

### `TASK_TIMEOUT` error

- Fadr stem tasks can take 20–60 seconds for longer tracks
- Increase `FADR_POLL_TIMEOUT_S` (default: 300) if processing very long files
- Check Fadr's status page for service disruptions

### `DOWNSTREAM_ERROR` with HTTP 401

- Your `FADR_API_KEY` is invalid or expired
- Ensure your Fadr Plus subscription is active

### `DOWNSTREAM_ERROR` with HTTP 402

- You have exceeded your Fadr billing threshold
- Check your usage at fadr.com

### High latency

- Fadr stem tasks typically complete in 20–40 seconds
- The server polls every `FADR_POLL_INTERVAL_S` (default: 5s); reduce to 3s for faster responses
- Network latency between the server and Fadr adds overhead

---

## License

MIT — see [LICENSE](LICENSE)

---

## Docs Index

- [docs/api_contract.md](docs/api_contract.md) — Tool schemas, input/output definitions
- [docs/architecture.md](docs/architecture.md) — Layer design, data flow, design decisions
- [docs/security.md](docs/security.md) — Key handling, URL validation, logging rules
- [docs/development.md](docs/development.md) — Local setup, testing, linting, CI
