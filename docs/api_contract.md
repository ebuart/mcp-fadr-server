# API Contract — MCP Fadr Server

> Version: 0.1.0
> Last updated: 2026-02-26

This document is the authoritative schema reference for all MCP tools exposed by this server.
No tool may return a response that deviates from the schemas defined here.

---

## Standard Response Envelope

Every tool returns exactly this top-level structure:

```json
{
  "success": true,
  "data": { },
  "error": null
}
```

Or on failure:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {}
  }
}
```

### Envelope JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["success", "data", "error"],
  "additionalProperties": false,
  "properties": {
    "success": { "type": "boolean" },
    "data":    { "oneOf": [{ "type": "object" }, { "type": "null" }] },
    "error":   {
      "oneOf": [
        { "type": "null" },
        {
          "type": "object",
          "required": ["code", "message", "details"],
          "additionalProperties": false,
          "properties": {
            "code":    { "type": "string" },
            "message": { "type": "string" },
            "details": { "oneOf": [{ "type": "object" }, { "type": "null" }] }
          }
        }
      ]
    }
  }
}
```

### Error Codes

| Code | Meaning |
|---|---|
| `INVALID_INPUT` | Input failed schema validation |
| `INVALID_URL` | `audio_url` scheme or format is rejected |
| `UPLOAD_FAILED` | Could not fetch / upload the source audio to Fadr |
| `TASK_FAILED` | Fadr async task ended with an error status |
| `TASK_TIMEOUT` | Polling exceeded the configured timeout |
| `DOWNSTREAM_ERROR` | Fadr API returned an unexpected HTTP error |
| `INTERNAL_ERROR` | Unhandled server-side error |

---

## Underlying Fadr API

All three tools share a single Fadr processing pipeline:

| Step | Fadr Endpoint | Method |
|---|---|---|
| 1. Get presigned upload URL | `/assets/upload2` | POST |
| 2. Upload audio binary | `<presigned URL>` | PUT |
| 3. Register asset | `/assets` | POST |
| 4. Start stem task | `/assets/analyze/stem` | POST |
| 5. Poll task status | `/tasks/:_id` | GET |
| 6. Get download URL | `/assets/download/:_id/:type` | GET |

Base URL: `https://api.fadr.com`
Authentication: `Authorization: Bearer <FADR_API_KEY>`

The `model` field in step 4 is always `"main"` for MVP tools.
The `"main"` model produces:
- 5 audio stems (vocals, bass, drums, melodies, instrumental)
- MIDI for each non-drum stem + a chord progression MIDI
- Key detection, tempo detection, chord progression

---

## Tool 1: `separate_stems`

### Description

Downloads audio from the given URL, uploads it to Fadr, and runs stem separation.
Returns presigned download URLs for each separated stem.

### Input Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["audio_url"],
  "additionalProperties": false,
  "properties": {
    "audio_url": {
      "type": "string",
      "format": "uri",
      "description": "Publicly accessible URL of the source audio file (https only). Supported formats: mp3, wav, aac, flac, ogg, m4a."
    },
    "quality": {
      "type": "string",
      "enum": ["preview", "hqPreview", "download"],
      "default": "hqPreview",
      "description": "Download quality for stem files. 'preview' = medium MP3, 'hqPreview' = high-quality MP3, 'download' = lossless WAV."
    }
  }
}
```

### Output `data` Schema (on success)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["stems", "job_id"],
  "additionalProperties": false,
  "properties": {
    "job_id": {
      "type": "string",
      "description": "Fadr task _id for auditability."
    },
    "processing_time_ms": {
      "type": ["integer", "null"],
      "description": "Wall-clock time from task submission to completion in milliseconds."
    },
    "stems": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["name", "url"],
        "additionalProperties": false,
        "properties": {
          "name": {
            "type": "string",
            "description": "Stem label, e.g. 'vocals', 'bass', 'drums', 'melodies', 'instrumental'."
          },
          "url": {
            "type": "string",
            "format": "uri",
            "description": "Presigned download URL for this stem. Valid for a limited time."
          }
        }
      }
    }
  }
}
```

### Example Response

```json
{
  "success": true,
  "data": {
    "job_id": "64f1a2b3c4d5e6f7a8b9c0d1",
    "processing_time_ms": 18420,
    "stems": [
      { "name": "vocals",       "url": "https://storage.fadr.com/signed/vocals-xyz.mp3?token=..." },
      { "name": "bass",         "url": "https://storage.fadr.com/signed/bass-xyz.mp3?token=..." },
      { "name": "drums",        "url": "https://storage.fadr.com/signed/drums-xyz.mp3?token=..." },
      { "name": "melodies",     "url": "https://storage.fadr.com/signed/melodies-xyz.mp3?token=..." },
      { "name": "instrumental", "url": "https://storage.fadr.com/signed/instrumental-xyz.mp3?token=..." }
    ]
  },
  "error": null
}
```

---

## Tool 2: `extract_midi`

### Description

Downloads audio from the given URL, uploads it to Fadr, and extracts MIDI representations
of each stem and the chord progression. MIDI extraction is part of the same stem task as
`separate_stems`; this tool returns only the MIDI outputs.

### Input Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["audio_url"],
  "additionalProperties": false,
  "properties": {
    "audio_url": {
      "type": "string",
      "format": "uri",
      "description": "Publicly accessible URL of the source audio file (https only). Supported formats: mp3, wav, aac, flac, ogg, m4a."
    }
  }
}
```

### Output `data` Schema (on success)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["job_id", "midi_files"],
  "additionalProperties": false,
  "properties": {
    "job_id": {
      "type": "string",
      "description": "Fadr task _id for auditability."
    },
    "processing_time_ms": {
      "type": ["integer", "null"]
    },
    "midi_files": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["name", "url"],
        "additionalProperties": false,
        "properties": {
          "name": {
            "type": "string",
            "description": "MIDI track label, e.g. 'vocals', 'bass', 'melodies', 'chord_progression'."
          },
          "url": {
            "type": "string",
            "format": "uri",
            "description": "Presigned download URL for this MIDI file."
          }
        }
      }
    },
    "metadata": {
      "type": ["object", "null"],
      "description": "Optional extra metadata returned by Fadr (e.g. sample rate, beat grid).",
      "additionalProperties": true
    }
  }
}
```

### Example Response

```json
{
  "success": true,
  "data": {
    "job_id": "64f1a2b3c4d5e6f7a8b9c0d2",
    "processing_time_ms": 22100,
    "midi_files": [
      { "name": "vocals",           "url": "https://storage.fadr.com/signed/vocals-midi.mid?token=..." },
      { "name": "bass",             "url": "https://storage.fadr.com/signed/bass-midi.mid?token=..." },
      { "name": "melodies",         "url": "https://storage.fadr.com/signed/melodies-midi.mid?token=..." },
      { "name": "chord_progression","url": "https://storage.fadr.com/signed/chords-midi.mid?token=..." }
    ],
    "metadata": {
      "sample_rate": 44100,
      "beat_grid": []
    }
  },
  "error": null
}
```

---

## Tool 3: `analyze_music`

### Description

Downloads audio from the given URL, uploads it to Fadr, and returns high-level musical analysis:
key, tempo, time signature, and chord progression. Analysis is derived from the same stem task
as the other tools.

### Input Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["audio_url"],
  "additionalProperties": false,
  "properties": {
    "audio_url": {
      "type": "string",
      "format": "uri",
      "description": "Publicly accessible URL of the source audio file (https only). Supported formats: mp3, wav, aac, flac, ogg, m4a."
    }
  }
}
```

### Output `data` Schema (on success)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["job_id", "key", "tempo_bpm", "chord_progression"],
  "additionalProperties": false,
  "properties": {
    "job_id": {
      "type": "string"
    },
    "processing_time_ms": {
      "type": ["integer", "null"]
    },
    "key": {
      "type": "string",
      "description": "Detected musical key, e.g. 'C major', 'A minor'."
    },
    "tempo_bpm": {
      "type": "number",
      "minimum": 20,
      "maximum": 300,
      "description": "Detected tempo in beats per minute."
    },
    "time_signature": {
      "type": ["string", "null"],
      "description": "Time signature if available, e.g. '4/4', '3/4'."
    },
    "chord_progression": {
      "type": "array",
      "description": "Ordered list of detected chords.",
      "items": {
        "type": "object",
        "required": ["chord"],
        "additionalProperties": false,
        "properties": {
          "chord": {
            "type": "string",
            "description": "Chord symbol, e.g. 'Am', 'G', 'Fmaj7'."
          },
          "start_beat": {
            "type": ["number", "null"],
            "description": "Beat position where this chord begins (if provided by Fadr)."
          },
          "duration_beats": {
            "type": ["number", "null"],
            "description": "Duration in beats (if provided by Fadr)."
          }
        }
      }
    }
  }
}
```

### Example Response

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
      { "chord": "Am",   "start_beat": 1,  "duration_beats": 4 },
      { "chord": "F",    "start_beat": 5,  "duration_beats": 4 },
      { "chord": "C",    "start_beat": 9,  "duration_beats": 4 },
      { "chord": "G",    "start_beat": 13, "duration_beats": 4 }
    ]
  },
  "error": null
}
```

---

## Notes on Fadr Task Lifecycle

All three tools share the same underlying Fadr stem task. The service layer runs the full
pipeline but returns only the subset of data relevant to the tool called.

If the caller needs both stems and analysis for the same track, two separate tool calls will
trigger two separate Fadr tasks (and two billing events). Response caching is out of scope
for MVP 0.1.0.

Presigned download URLs returned by Fadr expire. Clients should download assets promptly.
Exact TTL is not documented by Fadr and should not be assumed.
