## Why

The XLSX import endpoint previously blocked until all files were processed, then returned a single JSON response. For large batches of files the request could hang for many seconds with no feedback, and a single file error would roll back the entire import. The frontend had no way to show users how many files had been processed or report per-file results.

## What Changes

- Replace the blocking JSON response on `POST /api/import/xlsx` with a `StreamingResponse` that emits **Server-Sent Events** (`text/event-stream`)
- Add three event types: `progress` (before each file), `file_done` (after each file), `complete` (final summary)
- Switch from a single commit/rollback for all files to **per-file commit/rollback**, so one bad file does not undo the others
- Read all `UploadFile` contents eagerly before the generator starts (FastAPI closes handles when the endpoint returns)

## Capabilities

### New Capabilities
- `import-xlsx-sse-progress`: Real-time SSE progress stream for XLSX import, enabling frontend progress bars and per-file result reporting

### Modified Capabilities
- `import-xlsx`: The existing import endpoint now streams instead of returning a plain JSON object; the `complete` event summary payload is backward-compatible with the old response shape

## Impact

- **Router**: `app/routers/import_xlsx.py` — endpoint signature changed to `async def`, response wrapped in `StreamingResponse`, per-file try/commit/rollback added, `_sse()` helper added
- **Response shape**: HTTP status is always `200` once streaming begins; auth/validation errors still return standard `4xx` before streaming starts
- **Frontend**: Must switch from a plain `fetch().then(r => r.json())` to `fetch()` + `ReadableStream` chunk parsing (cannot use `EventSource` as it is GET-only)
