"""Epilogue's web surface: the survivor's dashboard and a small JSON API.

The dashboard is intentionally not an "app to manage". It exists for three
moments: the intake conversation, the rare decision that genuinely needs a
human, and — whenever the family wants it — proof of everything that was
handled quietly on their behalf.

A server-sent-events feed streams the audit trail live, so during intake and
work cycles you can watch the agents think with their hands.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import db_path, make_model
from .domain import AuditEvent
from .engine import Vigil
from .engine import resolve_decision as engine_resolve_decision
from .ledger import Ledger
from .runtime import DEFAULT_VAULT, vault_status


def _find_web_dir() -> Path:
    """Locate the static frontend in source checkouts, Docker images, and
    installed packages alike (EPILOGUE_WEB_DIR overrides)."""
    candidates = [
        os.environ.get("EPILOGUE_WEB_DIR"),
        Path(__file__).resolve().parent.parent.parent / "web",  # src layout
        Path.cwd() / "web",  # Docker / running from a checkout
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    raise RuntimeError("web/ directory not found — set EPILOGUE_WEB_DIR")


WEB_DIR = _find_web_dir()


def require_access(request: Request) -> None:
    """When EPILOGUE_ACCESS_CODE is set (public demo hosting), mutating
    endpoints require the code — so a shared URL can't spend the host's
    model credits. Reads stay open; the code travels as a header the UI
    collects once and remembers."""
    code = os.environ.get("EPILOGUE_ACCESS_CODE")
    if code and request.headers.get("x-epilogue-code") != code:
        raise HTTPException(401, "This shared demo requires an access code.")


class IntakeRequest(BaseModel):
    narrative: str
    documents: str


class ResolveRequest(BaseModel):
    option_id: str
    note: str = ""


class AdvanceRequest(BaseModel):
    days: int = 1


class AppState:
    def __init__(self) -> None:
        self.ledger = Ledger(db_path())
        self.vigil: Vigil | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.busy = threading.Lock()  # one agent workload at a time keeps the demo legible
        self.status = "idle"  # idle | intake | working
        self.ledger.on_event(self._fanout)

    def get_vigil(self) -> Vigil:
        if self.vigil is None:
            self.vigil = Vigil(
                self.ledger,
                make_model(),
                # Lower this on rate-limited free-tier keys (e.g. EPILOGUE_MAX_STEWARD_RUNS=3).
                max_steward_runs_per_tick=int(os.environ.get("EPILOGUE_MAX_STEWARD_RUNS", "6")),
            )
        return self.vigil

    def _fanout(self, event: AuditEvent) -> None:
        if self.loop is None:
            return
        payload = json.loads(event.model_dump_json())
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, payload)

    def announce(self, kind: str, summary: str) -> None:
        """Push a synthetic (non-persisted) event to the live feed."""
        if self.loop is None:
            return
        payload = {"kind": kind, "summary": summary, "actor": "Epilogue", "synthetic": True}
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, payload)


STATE = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Epilogue", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/meta")
def get_meta() -> JSONResponse:
    return JSONResponse({"access_code_required": bool(os.environ.get("EPILOGUE_ACCESS_CODE"))})


@app.get("/api/state")
def get_state() -> JSONResponse:
    ledger = STATE.ledger
    case = ledger.first_case()
    if case is None:
        return JSONResponse({"case": None, "status": STATE.status})
    tasks = [json.loads(t.model_dump_json()) for t in ledger.tasks_for_case(case.id)]
    decisions = [json.loads(d.model_dump_json()) for d in ledger.decisions_for_case(case.id)]
    timeline = [
        json.loads(e.model_dump_json())
        for e in ledger.audit_for_case(case.id, limit=250)
        if e.kind
        in ("letter_sent", "mail_received", "decision_opened", "decision_resolved", "status", "note")
    ]
    activity = [json.loads(e.model_dump_json()) for e in ledger.audit_for_case(case.id, limit=120)]
    return JSONResponse(
        {
            "case": json.loads(case.model_dump_json()),
            "stats": ledger.stats(case.id),
            "tasks": tasks,
            "decisions": decisions,
            "timeline": timeline,
            "activity": activity,
            "weekly_note": ledger.kv_get(f"weekly_note:{case.id}"),
            "vault": vault_status(ledger, case.id),
            "vault_initial": DEFAULT_VAULT,
            "status": STATE.status,
        }
    )


@app.get("/api/mail")
def get_mail() -> JSONResponse:
    """Full correspondence file — consumed by the test suite and external tools."""
    case = STATE.ledger.first_case()
    if case is None:
        return JSONResponse({"mail": []})
    return JSONResponse(
        {"mail": [json.loads(m.model_dump_json()) for m in STATE.ledger.mail_for_case(case.id)]}
    )


@app.get("/api/seed")
def get_seed() -> JSONResponse:
    from .demo_case import SEED_DOCUMENTS, SEED_NARRATIVE

    return JSONResponse({"narrative": SEED_NARRATIVE, "documents": SEED_DOCUMENTS})


def _run_intake(narrative: str, documents: str) -> None:
    try:
        STATE.status = "intake"
        STATE.announce("status", "Epilogue is reading what you shared…")
        vigil = STATE.get_vigil()
        case = vigil.open_case(narrative, documents)
        STATE.announce("status", "The plan is ready. Beginning the first day's work…")
        vigil.tick(case.id)
        STATE.announce("case_ready", "Epilogue is on watch.")
    except Exception as exc:  # noqa: BLE001
        # Never strand a half-open case: clear it so the intake form returns
        # and the family can simply press Begin again.
        STATE.ledger.reset()
        STATE.announce("error", f"Intake failed: {exc}")
    finally:
        STATE.status = "idle"
        STATE.busy.release()


@app.post("/api/case")
def create_case(req: IntakeRequest, _: None = Depends(require_access)) -> JSONResponse:
    if STATE.ledger.first_case() is not None:
        raise HTTPException(409, "A case is already open. Reset first.")
    if not STATE.busy.acquire(blocking=False):
        raise HTTPException(409, "Epilogue is busy.")
    STATE.status = "intake"  # set before the thread starts so pollers never see a stale idle
    threading.Thread(target=_run_intake, args=(req.narrative, req.documents), daemon=True).start()
    return JSONResponse({"status": "started"})


def _run_advance(days: int) -> None:
    try:
        STATE.status = "working"
        case = STATE.ledger.first_case()
        vigil = STATE.get_vigil()
        for _ in range(days):
            day = STATE.ledger.advance_days(1)
            STATE.announce("clock", f"— {day.strftime('%A, %B')} {day.day} —")
            report = vigil.tick(case.id)
            if report.quiet:
                STATE.announce("status", "A quiet day. Nothing needed attention.")
        STATE.announce("done", "Caught up.")
    except Exception as exc:  # noqa: BLE001
        STATE.announce("error", f"Work cycle failed: {exc}")
    finally:
        STATE.status = "idle"
        STATE.busy.release()


@app.post("/api/clock/advance")
def advance_clock(req: AdvanceRequest, _: None = Depends(require_access)) -> JSONResponse:
    case = STATE.ledger.first_case()
    if case is None:
        raise HTTPException(400, "No case open.")
    if not STATE.busy.acquire(blocking=False):
        raise HTTPException(409, "Epilogue is busy.")
    STATE.status = "working"  # set before the thread starts so pollers never see a stale idle
    threading.Thread(target=_run_advance, args=(max(1, min(req.days, 14)),), daemon=True).start()
    return JSONResponse({"status": "started"})


def _run_reaction() -> None:
    try:
        STATE.status = "working"
        case = STATE.ledger.first_case()
        STATE.get_vigil().tick(case.id)
    except Exception as exc:  # noqa: BLE001
        STATE.announce("error", f"Work cycle failed: {exc}")
    finally:
        STATE.status = "idle"
        STATE.busy.release()


@app.post("/api/decisions/{decision_id}/resolve")
def resolve_decision(decision_id: str, req: ResolveRequest, _: None = Depends(require_access)) -> JSONResponse:
    decision = STATE.ledger.get_decision(decision_id)
    if decision is None:
        raise HTTPException(404, "No such decision.")
    if os.environ.get("EPILOGUE_PREVIEW"):
        # Preview mode has no model: record the resolution mechanically so the
        # UI flow can be felt end to end without credentials.
        engine_resolve_decision(STATE.ledger, decision_id, req.option_id, req.note)
        STATE.announce("status", "(Preview mode: with a model configured, Epilogue would resume this matter now.)")
        return JSONResponse({"status": "resolved"})
    STATE.get_vigil().resolve_decision(decision_id, req.option_id, req.note)
    if STATE.busy.acquire(blocking=False):
        STATE.status = "working"
        threading.Thread(target=_run_reaction, daemon=True).start()
    return JSONResponse({"status": "resolved"})


@app.post("/api/reset")
def reset(_: None = Depends(require_access)) -> JSONResponse:
    # Take the same busy lock the work cycles use, so a reset can never race a
    # cycle that is between acquiring the lock and doing its work.
    if STATE.status != "idle" or not STATE.busy.acquire(blocking=False):
        raise HTTPException(409, "Epilogue is mid-cycle; try again in a moment.")
    try:
        STATE.ledger.reset()
    finally:
        STATE.busy.release()
    STATE.announce("reset", "Case cleared.")
    return JSONResponse({"status": "reset"})


@app.get("/api/feed")
async def feed() -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    STATE.subscribers.add(queue)

    async def stream():
        try:
            yield "data: {}\n\n".format(json.dumps({"kind": "hello", "summary": "connected"}))
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            STATE.subscribers.discard(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
