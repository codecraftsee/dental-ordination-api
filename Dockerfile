# python:3.12-slim is multi-arch, so this builds unchanged on Hetzner ARM (CAX)
# and x86 (CX/CPX). Matches .python-version — the app uses `X | None` in
# function signatures (app/routers/import_xlsx.py), which needs 3.10+.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so the layer caches across code-only rebuilds.
# Every pinned dependency ships manylinux wheels for both aarch64 and x86_64,
# so no compiler toolchain is needed in the image.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# --workers 1 is deliberate, not a placeholder.
# app/main.py:67 runs Base.metadata.create_all() plus unconditional ALTER TABLE
# statements on every startup. Multiple workers would issue that DDL
# concurrently against the same Postgres schema and can deadlock. One worker is
# ample for client testing; revisit only after migrations move out of startup.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
