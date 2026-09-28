"""API 테스트 공통: 임시 SQLite에 실데이터(data_raw)를 적재하고 모델 배치까지 돌린 뒤 TestClient 제공."""
import atexit
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="miri_test_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)   # 테스트용 DB(수백 MB)를 실행마다 남기지 않게
os.environ["MIRI_NO_DOTENV"] = "1"               # 개발자 backend/.env 가 테스트에 섞이지 않게
os.environ["MIRI_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ.pop("MIRI_ADMIN_KEY", None)          # 관리자 API는 테스트에서 따로 켠다
os.environ["MIRI_FRONTEND_DIST"] = f"{_TMP}/no-dist"
os.environ.pop("KAKAO_REST_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.settings import settings  # noqa: E402
from app.services.engine import reset_state  # noqa: E402
from app.services.features_batch import build_features  # noqa: E402
from app.services.ingest import run_ingestion  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[2] / "data_raw"


@pytest.fixture(scope="session")
def ingest_results():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        res = run_ingestion(db, DATA_DIR, log=lambda *_: None)
        build_features(db, log=lambda *_: None)
    reset_state()
    return res


@pytest.fixture(scope="session")
def client(ingest_results):
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db(ingest_results):
    with SessionLocal() as s:
        yield s


BASE_ANALYSIS = {
    "area_code": "11680", "place_name": "강남역", "lat": 37.4981, "lng": 127.028, "radius_m": 500,
    "budget": 80_000_000, "monthly_rent_limit": 3_000_000, "labor_cost": 2_500_000, "business_goal": "안정형",
}


def device(name: str) -> dict:
    """테스트용 '브라우저': 이름마다 다른 저장 키(X-Device-Key) 헤더 — 화면은 브라우저마다 임의의 키를 만들어 보낸다."""
    return {"X-Device-Key": hashlib.sha256(name.encode()).hexdigest()}
