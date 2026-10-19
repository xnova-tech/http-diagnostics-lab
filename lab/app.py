"""A small, predictable HTTP surface for local diagnostics."""

import asyncio

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, RedirectResponse

app = FastAPI(title="XNova HTTP diagnostics lab", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items/42")
async def item() -> dict[str, object]:
    return {"id": 42, "name": "sample"}


@app.get("/unavailable")
async def unavailable() -> JSONResponse:
    return JSONResponse({"status": "unavailable"}, status_code=503)


@app.get("/redirect")
async def redirect() -> RedirectResponse:
    return RedirectResponse(url="/health", status_code=302)


@app.get("/slow")
async def slow(delay: float = Query(default=0.5, ge=0, le=2)) -> dict[str, object]:
    await asyncio.sleep(delay)
    return {"status": "ok", "delay": delay}
