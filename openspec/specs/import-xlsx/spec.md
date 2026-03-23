# Spec: XLSX Import — SSE Streaming

## Endpoint

```
POST /api/import/xlsx
Authorization: Bearer <admin token>
Content-Type: multipart/form-data
```

**Auth:** Admin role required (`require_admin` dependency).
**Input:** One or more files under the `files` form field.
**Response:** `text/event-stream` — streams Server-Sent Events as files are processed.

---

## Behaviour

1. All uploaded file contents are read eagerly before streaming begins (UploadFile handles are closed by FastAPI once the endpoint returns, so reads must happen before the generator starts).
2. Doctors are pre-loaded once and indexed by first-name initial for visit-row resolution.
3. Each file is processed independently — a failure in one file does not affect others (per-file commit/rollback).
4. The stream always ends with a `complete` event, even on catastrophic failure.

### Excel file structure expected

| Row (0-indexed) | Column C (index 2) | Content |
|---|---|---|
| 2 | gender | `m`/`M` = male, `z`/`Z`/`ž` = female |
| 3 | last_name | |
| 4 | first_name | |
| 5 | parent_name | |
| 6 | date_of_birth | `dd.mm.yyyy.` string or Excel date |
| 7 | address | |
| 8 | city | |
| 9 | phone | |
| 10 | email | |
| 14+ | visit rows | col 0=date, col 2=diagnosis, col 4=treatment, col 5=doctor initial, col 6-7=price |

Minimum 14 rows required; files shorter than this are skipped with an error.

### Patient matching

Lookup by `first_name` (case-insensitive) + `last_name` (case-insensitive) + `date_of_birth`. If no match, a new patient is created.

### Visit deduplication

A visit row is skipped if a visit already exists for the same `patient_id`, `date`, `diagnosis_notes`, and `treatment_notes`.

### Visit rows — date carry-forward

If a row has no date in column 0, the last seen valid date is reused (continuation rows for the same visit date).

---

## SSE Event Reference

All events use the `data:` line format with `\n\n` terminator. The `type` field in the JSON payload identifies the event.

### `progress`
Emitted before processing begins for each file.

```json
{
  "type": "progress",
  "current": 1,
  "total": 3,
  "file": "patient_smith.xlsx",
  "status": "processing"
}
```

### `file_done`
Emitted after each file completes (whether successful or not).

```json
{
  "type": "file_done",
  "current": 1,
  "total": 3,
  "file": "patient_smith.xlsx",
  "patients_created": 1,
  "patients_found": 0,
  "visits_created": 14,
  "visits_skipped": 2,
  "errors": []
}
```

`errors` is an empty array on success; non-fatal per-file errors (invalid gender, invalid DOB, missing doctor) are included here without aborting the stream.

### `complete`
Emitted once after all files are processed.

```json
{
  "type": "complete",
  "summary": {
    "patients_created": 2,
    "patients_found": 1,
    "visits_created": 31,
    "visits_skipped": 3,
    "files_processed": 3,
    "errors": ["patient_jones.xlsx: Invalid gender 'x', defaulting to male"]
  }
}
```

The `summary` shape matches the response that the old (non-streaming) version of this endpoint returned, for backward compatibility.

---

## Response Headers

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

`X-Accel-Buffering: no` disables Nginx proxy buffering so chunks are flushed immediately.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Auth failure / missing files | FastAPI raises `HTTPException` before streaming starts → normal `4xx` JSON response |
| Per-file processing error | Caught inside generator, error added to `file_errors`, `file_done` event emitted, processing continues |
| Catastrophic generator crash | Top-level `try/except` emits a `complete` event with the fatal error message before the stream ends |

---

## Implementation

- **Router file:** `app/routers/import_xlsx.py`
- **Key helpers:** `parse_date`, `parse_gender`, `parse_price`, `extract_tooth_number`, `cell_str`
- **SSE helper:** `_sse(data: dict) -> str` — formats a single SSE line
- **Frontend integration:** Use `fetch()` + `ReadableStream` (not `EventSource`). Split chunks on `\n\n`, strip `data:` prefix, parse JSON.
