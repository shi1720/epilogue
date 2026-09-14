"""Private demo workspaces, durable background work, and the survivor dashboard."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .auth import hosted, identity, session_cookie
from .budget import Budget, BudgetExceeded, BudgetModel, RunPaused
from .config import data_dir, db_path, make_model
from .engine import Vigil
from .engine import resolve_decision as engine_resolve_decision
from .ledger import Ledger
from .runtime import DEFAULT_VAULT, vault_status
from .storage import FirestoreStore, LocalStore

log = logging.getLogger("epilogue")
WEB_DIR = Path(os.environ.get("EPILOGUE_WEB_DIR", Path(__file__).resolve().parents[2] / "web"))
if not WEB_DIR.is_dir():
    WEB_DIR = Path.cwd() / "web"
STORE = None
CONTEXTS = {}
CONTEXT_LOCK = threading.RLock()
WORK_SLOTS = threading.BoundedSemaphore(3)
LOOP = None


def store():
    global STORE
    if STORE is None:
        STORE = FirestoreStore() if hosted() else LocalStore(data_dir() / "accounts.db")
    return STORE


def account_key(uid):
    return hashlib.sha256(uid.encode()).hexdigest()


def safe_error(exc):
    if isinstance(exc, (BudgetExceeded, RunPaused)):
        return str(exc)
    name, message = type(exc).__name__.lower(), str(exc).lower()
    if "insufficient_quota" in message or "billing" in message:
        return "The model provider has no available credit. Your work is saved. The demo host needs to update billing."
    if "authentication" in name or "api_key" in message or "401" in message:
        return "The model connection could not be authenticated. Your work is saved. The demo host needs to update its API key."
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "The model provider is missing from this deployment. The demo host needs to redeploy the app."
    if "429" in message or "throttl" in name:
        return "The model provider is busy. Your progress is saved; try Continue in a moment."
    if "timeout" in name or "timed out" in message:
        return "The model took too long to respond. Your progress is saved; choose Continue to retry."
    return "This work session was interrupted. Your progress is saved; choose Continue to retry."


class IntakeRequest(BaseModel):
    narrative: str = Field(min_length=10, max_length=12000)
    documents: str = Field(default="", max_length=80000)

    @field_validator("narrative", "documents", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResolveRequest(BaseModel):
    option_id: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class AdvanceRequest(BaseModel):
    days: int = Field(default=1, ge=1, le=14, strict=True)


class LoginRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=10000)


class AppState:
    def __init__(self, uid="local", generation="initial"):
        self.uid, self.generation = uid, generation
        records = store().records(uid, generation) if hosted() else None
        path = ":memory:" if hosted() else (db_path() if uid == "local" else data_dir() / f"{uid}-{generation}.db")
        self.ledger = Ledger(path, records=records)
        self.vigil = None
        self.busy = threading.Lock()
        self.status = "idle"
        self.error = None
        self.run_id = None
        self.loaded_revision = store().get(uid).get("finished_at")
        self.stop = threading.Event()
        self.subscribers = set()
        self.loop = None
        self.ledger.on_event(lambda event: self.broadcast(json.loads(event.model_dump_json())))

    def metadata(self):
        row = store().get(self.uid)
        operation = row.get("operation", {})
        status = self.status
        error = self.error or row.get("last_error")
        if hosted() and operation:
            if operation.get("expires", 0) > time.time():
                status = operation["status"]
            else:
                status = "idle"
                error = error or {"id": operation["id"], "message": "The previous session stopped. Your saved progress is ready to continue."}
        return {"status": status, "error": error, "budget": Budget(store(), self.uid).summary(),
                "intake_complete": bool(self.ledger.kv_get("intake_planned"))}

    def get_vigil(self):
        if self.vigil is None:
            model = make_model()
            if os.environ.get("EPILOGUE_MODEL_PROVIDER") == "openai":
                model = BudgetModel(model, Budget(store(), self.uid), self.should_stop)
            self.vigil = Vigil(self.ledger, model,
                               max_steward_runs_per_tick=int(os.environ.get("EPILOGUE_MAX_STEWARD_RUNS", "5")))
        return self.vigil

    def broadcast(self, payload):
        loop = self.loop or LOOP
        if loop:
            def deliver():
                for queue in tuple(self.subscribers):
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(payload)
            loop.call_soon_threadsafe(deliver)

    def announce(self, kind, summary):
        self.broadcast({"id": uuid.uuid4().hex, "kind": kind, "summary": summary,
                        "actor": "Epilogue", "synthetic": True})

    def should_stop(self):
        operation = store().get(self.uid).get("operation", {})
        return (self.stop.is_set() or operation.get("id") != self.run_id
                or operation.get("pause", False) or operation.get("expires", 0) < time.time())

    def heartbeat(self, done):
        while not done.wait(15):
            try:
                def renew(rows):
                    operation = rows[0].get("operation", {})
                    if operation.get("id") == self.run_id:
                        operation["expires"] = time.time() + 180
                store().transact([self.uid], renew)
            except Exception:
                self.stop.set()
                return

    def acquire(self, status):
        if self.status != "idle" or not self.busy.acquire(blocking=False):
            raise HTTPException(409, "A work session is already running. Its progress appears below.")
        if not WORK_SLOTS.acquire(blocking=False):
            self.busy.release()
            raise HTTPException(429, "The demo is helping a few other testers. Try again in a moment.")
        run_id = uuid.uuid4().hex
        try:
            def claim(rows):
                row = rows[0]
                if row.get("operation", {}).get("expires", 0) > time.time():
                    raise HTTPException(409, "A work session is already running. Please let it finish.")
                row["operation"] = {"id": run_id, "status": status, "expires": time.time() + 180}
                row["last_error"] = None
            store().transact([self.uid], claim)
        except BaseException:
            WORK_SLOTS.release()
            self.busy.release()
            raise
        self.status, self.run_id, self.error = status, run_id, None
        self.stop.clear()
        # A fresh metered model gets a fresh bounded work session, not fresh credit.
        if self.vigil and isinstance(self.vigil.model, BudgetModel):
            self.vigil = None

    def finish(self, error=None):
        self.error = error
        completed = time.time_ns()
        def finish(rows):
            if rows[0].get("operation", {}).get("id") == self.run_id:
                rows[0]["operation"] = {}
                rows[0]["last_error"] = error
                rows[0]["finished_at"] = completed
        try:
            store().transact([self.uid], finish)
        finally:
            self.loaded_revision = completed
            self.status = "idle"
            WORK_SLOTS.release()
            self.busy.release()
            self.announce("done", "Progress saved." if not error else error["message"])


STATE = AppState()


def context(request: Request, user: Annotated[dict, Depends(identity)]):
    if not hosted():
        return STATE
    uid = account_key(user["uid"])
    with CONTEXT_LOCK:
        row = store().get(uid)
        generation = row.get("generation", "initial")
        existing = CONTEXTS.get(uid)
        # Refresh after another revision's work, or when switching generations.
        operation_id = row.get("operation", {}).get("id")
        if (existing is None or existing.generation != generation
                or (operation_id and operation_id != existing.run_id)
                or (not operation_id and existing.loaded_revision != row.get("finished_at"))):
            existing = AppState(uid, generation)
            CONTEXTS[uid] = existing
        return existing


def require_access(request: Request):
    # Backward-compatible private/local installations can still use a styled access dialog.
    code = os.environ.get("EPILOGUE_ACCESS_CODE")
    if code and not hosted() and request.headers.get("x-epilogue-code") != code:
        raise HTTPException(401, "Enter the access code supplied by the demo host.")


@asynccontextmanager
async def lifespan(app):
    global LOOP
    LOOP = asyncio.get_running_loop()
    STATE.loop = LOOP
    yield
    LOOP = None


app = FastAPI(title="Epilogue", lifespan=lifespan)


@app.middleware("http")
async def protections(request, call_next):
    if request.method == "POST":
        if int(request.headers.get("content-length", "0") or 0) > 150000:
            return JSONResponse({"detail": "Please share fewer than 80,000 characters of documents."}, status_code=413)
        origin = request.headers.get("origin")
        allowed = {f"https://{request.headers.get('host')}"}
        allowed.update(os.environ.get("EPILOGUE_ALLOWED_ORIGINS", "").split(","))
        if origin and origin not in allowed and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Please use the app's own page to make this request."}, status_code=403)
        if hosted() and request.headers.get("x-epilogue-request") != "1":
            return JSONResponse({"detail": "Refresh the app and try again."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    return JSONResponse({"detail": "Please check the form: add a short description (10–12,000 characters), and keep documents under 80,000 characters."}, status_code=422)


@app.exception_handler(Exception)
async def unexpected(request, exc):
    error_id = uuid.uuid4().hex[:10]
    log.error("request_failed reference=%s type=%s", error_id, type(exc).__name__)
    return JSONResponse({"detail": "We couldn't complete that request. Please try again.", "reference": error_id}, status_code=500)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.2.0", "auth": "firebase" if hosted() else "local"}


@app.get("/api/meta")
def meta():
    return {"access_code_required": bool(os.environ.get("EPILOGUE_ACCESS_CODE")) and not hosted(),
            "auth_required": hosted(), "firebase": json.loads(os.environ.get("EPILOGUE_FIREBASE_CONFIG", "{}")),
            "allowance_usd": float(os.environ.get("EPILOGUE_ACCOUNT_BUDGET_USD", "3")),
            "preview": bool(os.environ.get("EPILOGUE_PREVIEW"))}


@app.post("/api/session")
def login(req: LoginRequest):
    if not hosted():
        raise HTTPException(400, "This local workspace does not require sign-in.")
    response = JSONResponse({"status": "signed_in"})
    response.set_cookie("__session", session_cookie(req.id_token), max_age=5 * 86400,
                        httponly=True, secure=True, samesite="lax", path="/")
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie("__session", path="/", secure=True, httponly=True, samesite="lax")
    return response


@app.get("/api/account")
def account(user: Annotated[dict, Depends(identity)], ctx: Annotated[AppState, Depends(context)]):
    return {"user": {k: v for k, v in user.items() if k != "uid"}, "budget": Budget(store(), ctx.uid).summary()}


def state_payload(ctx):
    ledger, metadata = ctx.ledger, ctx.metadata()
    case = ledger.first_case()
    if case is None:
        return {"case": None, **metadata}
    activity = [json.loads(e.model_dump_json()) for e in ledger.audit_for_case(case.id, limit=250)]
    return {"case": json.loads(case.model_dump_json()), "stats": ledger.stats(case.id),
            "tasks": [json.loads(t.model_dump_json()) for t in ledger.tasks_for_case(case.id)],
            "decisions": [json.loads(d.model_dump_json()) for d in ledger.decisions_for_case(case.id)],
            "timeline": [e for e in activity if e["kind"] in
                         ("letter_sent", "mail_received", "decision_opened", "decision_resolved", "status", "note")],
            "activity": activity[:120], "weekly_note": ledger.kv_get(f"weekly_note:{case.id}"),
            "vault": vault_status(ledger, case.id), "vault_initial": DEFAULT_VAULT, **metadata}


@app.get("/api/state")
def get_state(ctx: Annotated[AppState, Depends(context)]):
    return state_payload(ctx)


@app.get("/api/mail")
def get_mail(ctx: Annotated[AppState, Depends(context)]):
    case = ctx.ledger.first_case()
    return {"mail": [json.loads(m.model_dump_json()) for m in ctx.ledger.mail_for_case(case.id)] if case else []}


@app.get("/api/export")
def export(ctx: Annotated[AppState, Depends(context)]):
    payload = state_payload(ctx)
    case = ctx.ledger.first_case()
    payload['mail'] = [json.loads(m.model_dump_json()) for m in ctx.ledger.mail_for_case(case.id, limit=-1)] if case else []
    payload['audit'] = [json.loads(e.model_dump_json()) for e in ctx.ledger.audit_for_case(case.id, limit=-1)] if case else []
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="epilogue-case.json"'})


@app.get("/api/seed")
def get_seed():
    from .demo_case import SEED_DOCUMENTS, SEED_NARRATIVE
    return {"narrative": SEED_NARRATIVE, "documents": SEED_DOCUMENTS}


def run_work(ctx, mode, days=0):
    error = None
    finished = threading.Event()
    threading.Thread(target=ctx.heartbeat, args=(finished,), daemon=True).start()
    try:
        vigil = ctx.get_vigil()
        if mode == "intake" or not ctx.ledger.kv_get("intake_planned") and ctx.ledger.kv_get("intake_request"):
            req = json.loads(ctx.ledger.kv_get("intake_request"))
            ctx.announce("status", "Reading the story and making a plan…")
            vigil.open_case(req["narrative"], req["documents"])
            ctx.announce("status", "The plan is ready. Beginning the first day's work…")
        case = ctx.ledger.first_case()
        if case is None:
            raise ValueError("No case to resume")
        for _ in range(max(1, days)):
            if ctx.stop.is_set():
                raise RunPaused("The session is paused. Your progress is saved; choose Continue whenever you're ready.")
            if days:
                day = ctx.ledger.advance_days(1)
                ctx.announce("clock", f"Working through {day.strftime('%B %d')}…")
            vigil.tick(case.id)
        ctx.announce("case_ready", "Epilogue is on watch.")
    except Exception as exc:
        error = {"id": uuid.uuid4().hex[:10], "message": safe_error(exc)}
        log.error("work_failed reference=%s type=%s", error["id"], type(exc).__name__)
        ctx.announce("error", error["message"])
    finally:
        finished.set()
        ctx.finish(error)


def start(ctx, mode, days=0):
    threading.Thread(target=run_work, args=(ctx, mode, days), daemon=True).start()
    return {"status": "started"}


@app.post("/api/case", dependencies=[Depends(require_access)])
def create_case(req: IntakeRequest, ctx: Annotated[AppState, Depends(context)]):
    if ctx.ledger.first_case() is not None:
        raise HTTPException(409, "A case is already open. Continue it or start a new case.")
    ctx.acquire("intake")
    try:
        ctx.ledger.kv_set("intake_request", req.model_dump_json())
    except BaseException:
        ctx.finish()
        raise
    return start(ctx, "intake")


@app.post("/api/clock/advance", dependencies=[Depends(require_access)])
def advance_clock(req: AdvanceRequest, ctx: Annotated[AppState, Depends(context)]):
    if ctx.ledger.first_case() is None:
        raise HTTPException(400, "Open a case before advancing the clock.")
    if os.environ.get("EPILOGUE_PREVIEW"):
        raise HTTPException(400, "This is a saved preview. Start the live app to run the agent.")
    ctx.acquire("working")
    return start(ctx, "advance", req.days)


@app.post("/api/retry", dependencies=[Depends(require_access)])
def retry(ctx: Annotated[AppState, Depends(context)]):
    if not ctx.ledger.first_case() and not ctx.ledger.kv_get("intake_request"):
        raise HTTPException(400, "Add a case first.")
    if os.environ.get("EPILOGUE_PREVIEW"):
        raise HTTPException(400, "This preview does not make model calls.")
    ctx.acquire("working")
    return start(ctx, "retry")


@app.post("/api/pause", dependencies=[Depends(require_access)])
def pause(ctx: Annotated[AppState, Depends(context)]):
    ctx.stop.set()
    def mark(rows):
        if rows[0].get("operation"):
            rows[0]["operation"]["pause"] = True
    store().transact([ctx.uid], mark)
    return {"status": "pausing", "detail": "The agent will pause after its current model request."}


@app.post("/api/decisions/{decision_id}/resolve", dependencies=[Depends(require_access)])
def resolve_decision(decision_id: str, req: ResolveRequest, ctx: Annotated[AppState, Depends(context)]):
    decision = ctx.ledger.get_decision(decision_id)
    if decision is None:
        raise HTTPException(404, "That decision is not in your case.")
    if decision.status != "open":
        raise HTTPException(409, "This decision was already answered. The case has been refreshed.")
    if not any(o.id == req.option_id for o in decision.options):
        raise HTTPException(422, "Choose one of the options shown on this decision.")
    ctx.acquire("working")
    try:
        engine_resolve_decision(ctx.ledger, decision_id, req.option_id, req.note)
    except BaseException:
        ctx.finish()
        raise
    if os.environ.get("EPILOGUE_PREVIEW"):
        ctx.finish()
    else:
        start(ctx, "reaction")
    return {"status": "resolved"}


@app.post("/api/reset", dependencies=[Depends(require_access)])
def reset(ctx: Annotated[AppState, Depends(context)]):
    ctx.acquire("working")
    try:
        if hosted():
            generation = uuid.uuid4().hex
            store().put(ctx.uid, {"generation": generation})
            ctx.ledger = Ledger(":memory:", records=store().records(ctx.uid, generation))
            ctx.generation = generation
            ctx.ledger.on_event(lambda event: ctx.broadcast(json.loads(event.model_dump_json())))
        else:
            ctx.ledger.reset()
        ctx.vigil = None
        ctx.announce("reset", "Ready for a new case. Your remaining allowance is unchanged.")
    finally:
        ctx.finish()
    return {"status": "reset"}


@app.get("/api/feed")
async def feed(ctx: Annotated[AppState, Depends(context)]):
    queue = asyncio.Queue(maxsize=200)
    ctx.subscribers.add(queue)
    async def stream():
        try:
            yield 'data: {"kind":"hello","summary":"connected"}\n\n'
            # Hosting terminates long responses; close cleanly and let EventSource reconnect.
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            ctx.subscribers.discard(queue)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
