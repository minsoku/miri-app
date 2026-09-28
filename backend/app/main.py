"""MIRI API 서버.  실행: uvicorn app.main:app --reload  (문서: /docs)"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import __version__, errors
from .db import Base, SessionLocal, engine, migrate
from .routers import admin, analyses, areas, meta, reports
from .services.engine import EngineNotReady, get_state
from .settings import settings

log = logging.getLogger("miri")
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    for col in migrate(engine):
        log.warning("DB 구조 갱신(이전 버전 DB 호환): %s", col)
    try:
        with SessionLocal() as db:
            get_state(db)
    except EngineNotReady as e:
        log.warning("엔진 미준비: %s", e)
    yield


app = FastAPI(title="MIRI API", version=__version__, lifespan=lifespan,
              description="데이터 기반 상권 분석·업종 추천 서비스 MIRI의 REST API. 로그인 없이 누구나 쓰고, "
                          "저장 리포트는 브라우저마다 따로 보관한다(X-Device-Key 헤더). 금액 단위는 원(KRW).",
              openapi_url=f"{API_PREFIX}/openapi.json", docs_url="/docs", redoc_url="/redoc")
errors.install(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024)        # 지도 경계·분석 결과 JSON은 수백 KB → 압축


@app.exception_handler(EngineNotReady)
async def _not_ready(_, e: EngineNotReady):
    return JSONResponse(status_code=503, content={"error": {"code": "ENGINE_NOT_READY", "message": str(e)}})


for r in (meta.router, areas.router, analyses.router, reports.router, admin.router):
    app.include_router(r, prefix=API_PREFIX)

# 프론트엔드 빌드가 있으면 같은 서버에서 제공 (npm run build → frontend/dist)
if settings.frontend_dist.is_dir() and (settings.frontend_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def index():
        return FileResponse(settings.frontend_dist / "index.html")

    # '#/' 없이 연 화면 주소(/reports 등)는 errors._http가 404 대신 같은 화면으로 보낸다(API 주소는 JSON 404·405 그대로)
    app.state.spa = True
