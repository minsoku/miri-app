"""문서 산출물 생성: OpenAPI(JSON) + PostgreSQL/MySQL DDL.  사용: python scripts/export_docs.py ../docs"""
import json
import os
os.environ.setdefault("MIRI_NO_DOTENV", "1")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from app.db import Base
from app import models  # noqa: F401
from app.main import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "../docs")
out.mkdir(parents=True, exist_ok=True)
(out / "openapi.json").write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=1), encoding="utf-8")
for name, dialect in (("postgres", postgresql.dialect()), ("mysql", mysql.dialect())):
    parts = [f"-- MIRI ERD v2 DDL ({name}) — app/models.py 에서 자동 생성. 직접 고치지 말고 모델을 고친 뒤 다시 생성하세요.\n"]
    for t in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(t).compile(dialect=dialect)).strip() + ";\n")
        for ix in t.indexes:
            parts.append(str(CreateIndex(ix).compile(dialect=dialect)).strip() + ";\n")
    (out / f"schema_{name}.sql").write_text("\n".join(parts), encoding="utf-8")
print("저장:", out / "openapi.json", out / "schema_postgres.sql", out / "schema_mysql.sql")

# ── API.md: 실제 호출 예시를 임시 DB 사본에서 만들어 문서에 넣는다 ──
import shutil, tempfile  # noqa: E402
from importlib import reload  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.services import engine as _eng  # noqa: E402

src_db = Path(__file__).resolve().parent.parent / "miri.db"
if not src_db.exists():
    print("miri.db 없음 → API.md 예시는 건너뜀 (python scripts/init_data.py 먼저)")
    sys.exit(0)
tmp = tempfile.mkdtemp(prefix="miri_docs_")
import atexit  # noqa: E402
atexit.register(shutil.rmtree, tmp, ignore_errors=True)   # 예시용 DB 사본을 남기지 않게
import sqlite3  # noqa: E402
_s, _d = sqlite3.connect(src_db), sqlite3.connect(f"{tmp}/d.db")
_s.backup(_d)                       # 서버가 쓰는 중(WAL)이어도 일관된 사본
_d.close(); _s.close()
from app import db as _db  # noqa: E402
_db.engine = _db.make_engine(f"sqlite:///{tmp}/d.db")
_db.SessionLocal.configure(bind=_db.engine)
_db.migrate(_db.engine)             # 예전 버전으로 만든 miri.db 사본이어도 새 컬럼을 채워 두고 예시를 만든다
_eng.reset_state()


def trim(o, n=2):
    if isinstance(o, list):
        return [trim(x, n) for x in o[:n]] + (["…"] if len(o) > n else [])
    if isinstance(o, dict):
        return {k: trim(v, n) for k, v in o.items()}
    return o


ex = {}
with TestClient(app) as c:
    h = {"X-Device-Key": "docs-example-browser-key-0123456789abcdefgh"}    # 화면이 브라우저마다 만들어 보내는 저장 키(예시)
    ex["search"] = c.get("/api/v1/places/search", params={"q": "강남"}).json()
    ex["candidates"] = trim(c.get("/api/v1/areas/candidates", params={"lat": 37.4981, "lng": 127.028, "radius_m": 500, "place_name": "강남역"}).json())
    body = {"area_code": "11680", "place_name": "강남역", "lat": 37.4981, "lng": 127.028, "radius_m": 500, "user_type": "PRE_FOUNDER",
            "budget": 80000000, "monthly_rent_limit": 3000000, "labor_cost": 2500000, "business_goal": "안정형",
            "categories": ["외식업"], "interests": ["CS100010", "CS100008"]}
    ex["analysis_in"] = body
    a = c.post("/api/v1/analyses", json=body, headers=h).json()
    ex["analysis_out"] = trim(a, 1)
    aid = a["id"]
    ex["risk"] = trim(c.get(f"/api/v1/analyses/{aid}/risk/CS100010", headers=h).json(), 3)
    ex["be_in"] = {"industry_code": "CS100008", "avg_ticket": 9000, "owner_salary": 3000000}
    be = c.post(f"/api/v1/analyses/{aid}/breakeven", json=ex["be_in"], headers=h).json()
    ex["be_out"] = be
    rep = c.post(f"/api/v1/analyses/{aid}/reports", json={"industry_code": "CS100008", "break_even_id": be["id"]}, headers=h).json()
    ex["report"] = trim(rep, 3)
    ex["save"] = c.post("/api/v1/me/reports", json={"report_id": rep["id"], "memo": "1순위 후보"}, headers=h).json()
    ex["saved"] = c.get("/api/v1/me/reports", headers=h).json()
    ex["err_validation"] = c.post("/api/v1/analyses", json={k: v for k, v in body.items() if k != "budget"}).json()
    ex["err_cogs"] = c.post(f"/api/v1/analyses/{aid}/breakeven", json={"industry_code": "CS200028"}, headers=h).json()
    ex["err_device"] = c.post("/api/v1/me/reports", json={"report_id": rep["id"]}).json()
    ex["compare"] = trim(c.post("/api/v1/areas/compare", json={"area_codes": ["11680", "11650"], "industry_code": "CS100010"}).json(), 2)
tpl = (Path(__file__).resolve().parent / "api_md_template.md").read_text(encoding="utf-8")
J = lambda o: "```json\n" + json.dumps(o, ensure_ascii=False, indent=2) + "\n```"  # noqa: E731
for k, v in ex.items():
    tpl = tpl.replace("{{" + k + "}}", J(v))
(out / "API.md").write_text(tpl, encoding="utf-8")
print("저장:", out / "API.md")
