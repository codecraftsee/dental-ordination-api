## Context

The import endpoint accepted multiple XLSX files and returned one JSON response after processing them all. This caused two problems: users saw no progress for large batches, and a single file exception rolled back every other file's work. The frontend required a spinner with no meaningful status during the whole operation.

The app uses FastAPI with synchronous SQLAlchemy sessions but Uvicorn's async HTTP layer, making `StreamingResponse` with an `async def` generator the right fit — no external task queue or WebSocket complexity needed.

## Goals / Non-Goals

**Goals:**
- Emit a progress event before each file so the frontend can show a progress bar
- Emit a per-file result event after each file (success or partial error)
- Emit a final summary event matching the old response shape
- Isolate each file's DB work so one failure does not affect others
- Keep the response payload structure backward-compatible (the `complete.summary` object mirrors the old JSON response)

**Non-Goals:**
- WebSocket-based streaming (SSE is sufficient and simpler for a POST endpoint)
- Resumable or cancellable imports
- Parallel file processing (sequential is safe and predictable for DB writes)
- Frontend implementation (handled in the Angular application)

## Decisions

**1. `StreamingResponse` with an `async def` generator over WebSockets or background tasks**

SSE via `StreamingResponse` requires no extra dependencies and fits the request/response model naturally. WebSockets would add handshake complexity. Background tasks with polling would require a separate state store. SSE is the simplest option that delivers real-time events over a single HTTP connection.

**2. Eager file content reads before returning `StreamingResponse`**

FastAPI closes `UploadFile` handles when the endpoint function returns control to Uvicorn. Because `StreamingResponse` defers body generation to a generator that runs after the endpoint returns, any `await upload_file.read()` inside the generator would operate on a closed handle. Reading all contents into a `list[tuple[str, bytes]]` before returning is the only safe approach without restructuring FastAPI's lifecycle.

**3. Per-file commit/rollback instead of a single transaction**

With one transaction, an exception in file N rolls back files 1..N-1. Per-file commit means each file's patients and visits are durable as soon as the file succeeds, and only the failing file's work is rolled back. This matches user expectations: a bad file should not undo good imports.

**4. `complete` event summary mirrors old JSON response shape**

The old endpoint returned `{ patients_created, patients_found, visits_created, visits_skipped, files_processed, errors }`. The `complete` event wraps the same object under `summary`, preserving backward compatibility for any client that only cares about the final totals.

**5. `X-Accel-Buffering: no` header**

When deployed behind Nginx (e.g. Render), the proxy buffers responses by default and defeats streaming. This header disables Nginx buffering so each SSE chunk is flushed to the client immediately.

## Risks / Trade-offs

**[Streaming masks HTTP errors after stream begins]** → Once the first byte is sent, the HTTP status is fixed at `200`. Errors that occur mid-stream appear as `errors` fields in `file_done` or `complete` events, not as HTTP error codes. Frontend must check event payloads, not just HTTP status.

**[Generator holds DB session open for the full stream duration]** → The SQLAlchemy session passed via `Depends(get_db)` stays open until the generator is exhausted. For large batches this is a long-held connection. Acceptable given the expected file counts, but worth monitoring if connection pool exhaustion occurs under load.

**[No retry or resume]** → If the client disconnects mid-stream, the generator may continue running on the server side until Uvicorn detects the broken connection. Files already committed remain committed; the partial import is not automatically recoverable from the client side.
