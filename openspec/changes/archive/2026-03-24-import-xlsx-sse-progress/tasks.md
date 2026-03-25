## 1. Router — streaming response

- [x] 1.1 Change endpoint signature to `async def import_xlsx_files(...)` and import `StreamingResponse` from `fastapi.responses`
- [x] 1.2 Read all `UploadFile` contents eagerly into `list[tuple[str, bytes]]` before returning `StreamingResponse` (handles are closed after endpoint returns)
- [x] 1.3 Define `async def generate()` inner generator that yields SSE chunks
- [x] 1.4 Return `StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`

## 2. SSE helper

- [x] 2.1 Add `_sse(data: dict) -> str` helper that serialises a dict to `data: <json>\n\n`

## 3. Event emission

- [x] 3.1 Yield `progress` event (with `current`, `total`, `file`, `status`) before processing each file
- [x] 3.2 Yield `file_done` event (with `current`, `total`, `file`, per-file counts, `errors`) after each file
- [x] 3.3 Yield `complete` event (with `summary` dict) once after the loop exits
- [x] 3.4 Wrap the entire generator body in a top-level `try/except` that yields `complete` with the fatal error on unhandled exceptions

## 4. Per-file isolation

- [x] 4.1 Wrap each file's processing block in its own `try/except`
- [x] 4.2 Call `db.commit()` after each file succeeds
- [x] 4.3 Call `db.rollback()` in the per-file `except` block so only that file's writes are undone
