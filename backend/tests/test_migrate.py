"""이전 버전 DB 호환(migrate): 컬럼 추가 + NOT NULL 완화(SQLite 테이블 재작성). 워커 여러 개가 동시에 시작해도 안전해야 한다."""
import multiprocessing as mp
import sqlite3
import tempfile
from sqlalchemy import inspect
from app.db import Base, make_engine, migrate
from app import models  # noqa: F401


def _old_schema_db() -> str:
    """현재 모델로 만든 뒤 '이전 버전' 모양으로 되돌린다: empty_reason 없음, 입지 위험 컬럼 NOT NULL, 행 2개."""
    path = tempfile.mktemp(suffix=".db")
    eng = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    eng.dispose()
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("ALTER TABLE recommendation_results DROP COLUMN empty_reason")
    ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='risk_assessments'").fetchone()[0]
    old = (ddl.replace("location_risk_pct INTEGER,", "location_risk_pct INTEGER NOT NULL,")
              .replace("location_risk_level VARCHAR(30),", "location_risk_level VARCHAR(30) NOT NULL,")
              .replace("CREATE TABLE risk_assessments", "CREATE TABLE _old"))
    assert "location_risk_pct INTEGER NOT NULL" in old
    c.execute(old)
    c.execute("DROP TABLE risk_assessments")
    c.execute("ALTER TABLE _old RENAME TO risk_assessments")
    c.execute("CREATE INDEX ix_risk_assessments_request_id ON risk_assessments (request_id)")
    for i in (1, 2):
        c.execute("INSERT INTO risk_assessments (risk_id, request_id, category_id, area_id, risk_score, risk_level, pred_annual_rate,"
                  " location_risk_pct, location_risk_level, confidence, model_version, created_at)"
                  f" VALUES ({i}, 1, 1, 1, {40 + i}, '보통', 0.1, {10 * i}, '낮음', '높음', 'risk-v2.0', '2026-01-01')")
    c.commit()
    c.close()
    return path


def _run(path):
    eng = make_engine(f"sqlite:///{path}")
    try:
        return migrate(eng)
    finally:
        eng.dispose()


def _nullable(path):
    eng = make_engine(f"sqlite:///{path}")
    try:
        cols = {c["name"]: c for c in inspect(eng).get_columns("risk_assessments")}
        rr = {c["name"] for c in inspect(eng).get_columns("recommendation_results")}
        return cols["location_risk_pct"]["nullable"], cols["location_risk_level"]["nullable"], "empty_reason" in rr
    finally:
        eng.dispose()


def test_migrate_upgrades_old_db_and_keeps_rows():
    path = _old_schema_db()
    assert _nullable(path) == (False, False, False)
    done = _run(path)
    assert "recommendation_results.empty_reason" in done and any("location_risk_pct" in d for d in done)
    assert _nullable(path) == (True, True, True)
    c = sqlite3.connect(path)
    assert c.execute("SELECT risk_id, location_risk_pct FROM risk_assessments ORDER BY risk_id").fetchall() == [(1, 10), (2, 20)]
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert [r[1] for r in c.execute("PRAGMA index_list(risk_assessments)")] == ["ix_risk_assessments_request_id"]
    assert _run(path) == []                                      # 두 번째 실행은 할 일 없음


def test_migrate_concurrent_workers():
    """uvicorn --workers 2 처럼 두 프로세스가 동시에 migrate()를 불러도 둘 다 성공하고 결과는 한 번만 적용."""
    path = _old_schema_db()
    ctx = mp.get_context("fork")
    with ctx.Pool(3) as pool:
        results = pool.map(_run, [path] * 3)
    assert _nullable(path) == (True, True, True)
    assert sum("recommendation_results.empty_reason" in r for r in results) == 1
    assert sum(any("location_risk_pct" in d for d in r) for r in results) == 1
    c = sqlite3.connect(path)
    assert c.execute("SELECT count(*) FROM risk_assessments").fetchone()[0] == 2


def _old_saved_reports_db() -> str:
    """0.1(로그인 시절) 모양의 saved_reports: 브라우저 키 컬럼 없음, user_id NOT NULL, (user_id, report_id) 중복 방지,
    AUTOINCREMENT 번호는 5까지 썼다(4·5번은 지운 흔적)."""
    path = tempfile.mktemp(suffix=".db")
    eng = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    eng.dispose()
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("DROP TABLE saved_reports")
    c.execute("CREATE TABLE saved_reports (saved_report_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
              "report_id INTEGER NOT NULL, memo TEXT, created_at DATETIME NOT NULL, UNIQUE (user_id, report_id), "
              "FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE, "
              "FOREIGN KEY(report_id) REFERENCES action_reports (report_id) ON DELETE CASCADE)")
    c.execute("CREATE INDEX ix_saved_reports_user_id ON saved_reports (user_id)")
    c.execute("INSERT INTO users (user_id, email, password_hash, name, role, created_at) "
              "VALUES (1, 'old@example.com', 'x', '', 'PRE_FOUNDER', '2026-01-01')")
    c.execute("INSERT INTO saved_reports VALUES (1, 1, 10, '메모1', '2026-01-01')")
    c.execute("INSERT INTO saved_reports VALUES (3, 1, 11, NULL, '2026-01-02')")
    c.execute("UPDATE sqlite_sequence SET seq = 5 WHERE name = 'saved_reports'")
    c.commit()
    c.close()
    return path


def test_migrate_saved_reports_to_browser_keys():
    """로그인을 없앤 0.2: 옛 저장 목록 테이블에 브라우저 키 컬럼을 넣고 user_id를 NULL 허용으로 바꾼다(행·번호는 그대로)."""
    path = _old_saved_reports_db()
    done = _run(path)
    assert set(done) == {"saved_reports.device_key_hash", "saved_reports.user_id (NULL 허용)"}, done
    eng = make_engine(f"sqlite:///{path}")
    try:
        cols = {c["name"]: c for c in inspect(eng).get_columns("saved_reports")}
        assert cols["user_id"]["nullable"] and cols["device_key_hash"]["nullable"]
        idx = {i["name"] for i in inspect(eng).get_indexes("saved_reports")}
        assert {"ix_saved_reports_device_key_hash", "ix_saved_reports_user_id"} <= idx, idx
    finally:
        eng.dispose()
    c = sqlite3.connect(path)
    assert c.execute("SELECT saved_report_id, user_id, report_id, memo, device_key_hash FROM saved_reports ORDER BY 1").fetchall() \
        == [(1, 1, 10, "메모1", None), (3, 1, 11, None, None)]
    assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='saved_reports'").fetchall() == [(5,)]   # 지운 번호는 다시 안 씀
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    c.execute("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h1', 10, '2026-09-25')")
    assert c.execute("SELECT max(saved_report_id) FROM saved_reports").fetchone()[0] == 6
    c.execute("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h2', 10, '2026-09-25')")  # 다른 브라우저는 따로
    try:
        c.execute("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h1', 10, '2026-09-25')")
        raise AssertionError("같은 브라우저가 같은 리포트를 두 번 저장할 수 있으면 안 된다")
    except sqlite3.IntegrityError:
        pass
    c.close()
    assert _run(path) == []                                      # 두 번째 실행은 할 일 없음


def test_migrate_empty_saved_reports_keeps_sequence():
    """저장 행이 하나도 없어도(모두 지움) 옛 AUTOINCREMENT 번호를 이어 간다 — 지운 번호를 새 저장에 다시 쓰지 않게."""
    path = _old_saved_reports_db()
    c = sqlite3.connect(path)
    c.execute("DELETE FROM saved_reports")
    c.commit()
    c.close()
    _run(path)
    c = sqlite3.connect(path)
    assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='saved_reports'").fetchall() == [(5,)]
    c.execute("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h1', 10, '2026-09-25')")
    assert c.execute("SELECT saved_report_id FROM saved_reports").fetchall() == [(6,)]
    c.close()
