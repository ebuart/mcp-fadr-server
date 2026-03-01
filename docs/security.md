# Security — MCP Fadr Server

> Version: 0.1.0

This document defines the security baseline for the MCP Fadr Server.
All rules are mandatory. Any deviation requires explicit approval.

---

## 1. API Key Handling

### Rules

- The Fadr API key is loaded **exclusively from the `FADR_API_KEY` environment variable**
  (via `pydantic-settings`). It is never read from files, command-line arguments, or
  request parameters.
- The key is stored as a `SecretStr` (Pydantic v2) to prevent accidental serialization.
- The key is **never** included in:
  - Log records (any level)
  - Error messages returned to MCP clients
  - Exception `details` fields
  - Structured response envelopes
- When constructing the `Authorization` header, the key is accessed via `.get_secret_value()`
  immediately before use and never stored in a local variable that outlives the HTTP call.

### Verification

- `test_client_errors.py` includes a test asserting that no log record emitted during
  a failed request contains the substring of the API key.

---

## 2. URL Validation (SSRF Prevention)

All `audio_url` inputs are validated before any outbound HTTP request is made.

### Allowlist

| Check | Rule |
|---|---|
| Scheme | Must be in `ALLOWED_AUDIO_SCHEMES` (default: `https`) |
| Hostname | Must not resolve to a private/loopback/link-local IP range |
| Port | If specified, must be 443 (https) |
| Path | No additional restrictions, but length is bounded |

### Blocked Ranges (SSRF)

The URL validator resolves the hostname and checks against:
- Loopback: `127.0.0.0/8`, `::1`
- Private: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Link-local: `169.254.0.0/16`, `fe80::/10`
- Multicast: `224.0.0.0/4`
- Localhost aliases: `0.0.0.0`

If the hostname resolves to any blocked range, the tool returns:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_URL",
    "message": "The provided audio_url resolves to a disallowed address.",
    "details": null
  }
}
```

No details about the resolved IP are returned to the client.

### File Type Restriction

- The URL path extension is checked against a supported audio format allowlist:
  `mp3`, `wav`, `aac`, `flac`, `ogg`, `m4a`
- If the extension is missing or not in the allowlist, the request is rejected with
  `INVALID_URL` before any download attempt.
- Note: extension check is advisory — Fadr performs its own format validation on upload.

### Size Limit

- The download of `audio_url` is bounded by `MAX_AUDIO_SIZE_MB` (default: 100 MB).
- A `Content-Length` header check is performed before streaming; streams exceeding the
  limit are aborted.
- If no `Content-Length` is present, the stream is read with a byte counter and aborted
  on overflow.

---

## 3. Logging Rules

### What MAY be logged

- Tool name and job ID
- Task status transitions (pending → processing → done/failed)
- HTTP status codes (not response bodies)
- Processing durations
- Error codes from the error envelope

### What MUST NEVER be logged

- `FADR_API_KEY` or any portion of it
- Full request bodies containing presigned URLs (these are time-limited credentials)
- Presigned download URLs returned by Fadr
- The `audio_url` input (may contain tokens in query string)
- Any personally identifiable information

### Log Format

All logs are JSON objects. The logger factory in `utils/logging.py` enforces this.
Example record:
```json
{
  "timestamp": "2026-02-26T10:00:00Z",
  "level": "INFO",
  "logger": "mcp_fadr.stem_service",
  "message": "Stem task completed",
  "job_id": "64f1a2b3c4d5e6f7a8b9c0d1",
  "processing_time_ms": 18420
}
```

Free-text log lines that could interpolate sensitive values are prohibited.

---

## 4. Dependency Security

- Dependencies are pinned in `pyproject.toml` with minimum versions.
- `pip-audit` is recommended (but not enforced in CI for MVP) for vulnerability scanning.
- The project uses `httpx` for HTTP (not `requests`) — `httpx` enforces modern TLS by default.
- No dependency on `urllib` directly to avoid silent HTTP-to-HTTPS downgrades.

---

## 5. Transport Security

- The MCP server communicates over stdio (local transport). No network listener is opened
  by default.
- All outbound calls (Fadr API, audio_url download) use HTTPS exclusively.
- TLS certificate verification is enabled by default (`httpx` default). It MUST NOT be
  disabled in production.

---

## 6. Error Information Disclosure

- Internal exception messages are never forwarded to the MCP client verbatim.
- Only structured error codes and safe, human-readable messages are returned.
- The `details` field in the error envelope may include non-sensitive structured context
  (e.g., `{"field": "audio_url", "issue": "invalid_scheme"}`), but never stack traces,
  internal paths, or API keys.

---

## 7. ENV Var List

| Variable | Sensitivity | Notes |
|---|---|---|
| `FADR_API_KEY` | **Secret** | Never log, never expose |
| `FADR_BASE_URL` | Low | Override for testing only |
| `FADR_TIMEOUT_S` | Low | |
| `FADR_POLL_INTERVAL_S` | Low | |
| `FADR_POLL_TIMEOUT_S` | Low | |
| `FADR_MAX_RETRIES` | Low | |
| `LOG_LEVEL` | Low | |
| `ALLOWED_AUDIO_SCHEMES` | Low | Default: `https` |
| `MAX_AUDIO_SIZE_MB` | Low | Default: `100` |

Only `FADR_API_KEY` is secret. All others are safe to include in logs if needed.
