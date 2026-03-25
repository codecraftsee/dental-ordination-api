## MODIFIED Requirements

### Requirement: Import endpoint streams progress events instead of blocking
The `POST /api/import/xlsx` endpoint SHALL return a `text/event-stream` response that emits SSE events as files are processed, rather than blocking until all files are done and returning a single JSON object.

#### Scenario: Stream begins immediately
- **WHEN** an admin POSTs one or more XLSX files to `/api/import/xlsx`
- **THEN** the response SHALL start streaming with `Content-Type: text/event-stream` immediately
- **AND** the HTTP status SHALL be `200`

#### Scenario: Auth or validation failure before streaming
- **WHEN** a non-admin or unauthenticated user calls the endpoint
- **THEN** FastAPI SHALL return a `401` or `403` JSON response before any streaming begins

---

## ADDED Requirements

### Requirement: Progress event emitted before each file
Before processing each uploaded file, the endpoint SHALL emit a `progress` SSE event.

#### Scenario: Progress event shape
- **WHEN** the endpoint begins processing file N of M
- **THEN** it SHALL emit:
  ```json
  { "type": "progress", "current": N, "total": M, "file": "<filename>", "status": "processing" }
  ```

---

### Requirement: File-done event emitted after each file
After each file is processed (whether successful or not), the endpoint SHALL emit a `file_done` SSE event with per-file counts and any non-fatal errors.

#### Scenario: Successful file
- **WHEN** a file is processed without a fatal exception
- **THEN** a `file_done` event SHALL be emitted with counts and `"errors": []`

#### Scenario: File with non-fatal parse errors (invalid gender, invalid DOB, missing doctor initial)
- **WHEN** a file is processed but contains rows with invalid or missing data
- **THEN** a `file_done` event SHALL be emitted with `errors` listing the non-fatal issues
- **AND** valid rows from that file SHALL still be committed

#### Scenario: File-done event shape
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

---

### Requirement: Complete event emitted once after all files
After all files are processed, the endpoint SHALL emit a single `complete` SSE event with aggregated summary totals.

#### Scenario: Complete event shape
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

#### Scenario: Catastrophic generator failure
- **WHEN** an unexpected exception escapes the per-file loop
- **THEN** the top-level handler SHALL catch it, append a `"Fatal error: ..."` entry to `errors`, and still emit the `complete` event before the stream ends

---

### Requirement: Per-file commit/rollback isolation
Each file's database writes SHALL be committed independently. A failure in one file SHALL NOT roll back data already committed from previous files.

#### Scenario: One file fails, others succeed
- **WHEN** file 2 of 3 raises an unhandled exception during processing
- **THEN** all writes from file 1 SHALL remain committed in the database
- **AND** file 2's writes SHALL be rolled back
- **AND** processing SHALL continue with file 3

---

### Requirement: Response headers disable proxy buffering
The streaming response SHALL include headers that prevent intermediate proxies from buffering the SSE chunks.

#### Scenario: Nginx deployment
- **WHEN** the response is proxied through Nginx (e.g. Render)
- **THEN** the `X-Accel-Buffering: no` header SHALL instruct Nginx to flush chunks immediately
- **AND** `Cache-Control: no-cache` SHALL prevent caching of the stream
