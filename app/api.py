"""API FastAPI de orquestación con Redis, aprobación y métricas."""

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from langgraph.types import Command
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from app.workflow import build_workflow

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("multi_agent_api")
REQUESTS = Counter("agent_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("agent_http_duration_seconds", "Request duration", ["method", "path"])


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    require_approval: bool = False


class ApprovalRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    approved: bool


class ChatResponse(BaseModel):
    thread_id: str
    status: str
    answer: str | None = None
    pending: dict | None = None
    route_history: list[str] = Field(default_factory=list)


def authenticate(x_api_key: str | None = Header(default=None)) -> None:
    token = os.getenv("API_TOKEN", "")
    if not token:
        raise HTTPException(503, "API_TOKEN no configurado")
    if not x_api_key or not secrets.compare_digest(x_api_key, token):
        raise HTTPException(401, "Clave de API inválida")


def create_app(*, workflow=None, redis_client=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if workflow is not None:
            app.state.workflow = workflow
            app.state.redis_client = redis_client
            yield
            return
        from langgraph.checkpoint.redis import RedisSaver
        from redis import Redis

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        with RedisSaver.from_conn_string(url) as saver:
            saver.setup()
            client = Redis.from_url(url)
            client.ping()
            app.state.workflow = build_workflow(checkpointer=saver)
            app.state.redis_client = client
            yield
            client.close()

    app = FastAPI(title="API multiagente", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def measure(request: Request, call_next):
        start = time.perf_counter()
        path = request.url.path
        try:
            response = await call_next(request)
            return response
        finally:
            status = str(response.status_code) if "response" in locals() else "500"
            REQUESTS.labels(request.method, path, status).inc()
            LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
            logger.info("request method=%s path=%s status=%s", request.method, path, status)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        client = request.app.state.redis_client
        if client is not None:
            try:
                client.ping()
            except Exception as exc:
                raise HTTPException(503, "Redis no disponible") from exc
        return {"status": "ready"}

    @app.get("/metrics", dependencies=[Depends(authenticate)])
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/chat", dependencies=[Depends(authenticate)], response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        graph = request.app.state.workflow
        config = {"configurable": {"thread_id": body.thread_id}}
        if graph.get_state(config).next:
            raise HTTPException(409, "Conversación pendiente de aprobación")
        try:
            result = await asyncio.to_thread(
                graph.invoke,
                {"question": body.message, "require_approval": body.require_approval},
                config,
            )
        except Exception:
            logger.exception("agent_execution_failed thread_id=%s", body.thread_id)
            raise HTTPException(503, "No se pudo procesar la solicitud") from None
        if result.get("__interrupt__"):
            return {
                "thread_id": body.thread_id,
                "status": "pending",
                "pending": result["__interrupt__"][0].value,
            }
        return {
            "thread_id": body.thread_id,
            "status": result["status"],
            "answer": result["answer"],
            "route_history": result.get("route_history", []),
        }

    @app.post("/approve", dependencies=[Depends(authenticate)], response_model=ChatResponse)
    async def approve(body: ApprovalRequest, request: Request):
        graph = request.app.state.workflow
        config = {"configurable": {"thread_id": body.thread_id}}
        if "gate" not in graph.get_state(config).next:
            raise HTTPException(409, "No hay aprobación pendiente para este thread_id")
        try:
            result = await asyncio.to_thread(graph.invoke, Command(resume=body.approved), config)
        except Exception:
            logger.exception("approval_failed thread_id=%s", body.thread_id)
            raise HTTPException(503, "No se pudo reanudar la solicitud") from None
        return {
            "thread_id": body.thread_id,
            "status": result["status"],
            "answer": result["answer"],
            "route_history": result.get("route_history", []),
        }

    return app


app = create_app()
