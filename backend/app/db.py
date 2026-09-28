from __future__ import annotations
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .settings import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kw = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, future=True, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")          # SQLite는 FK 검사가 기본 꺼져 있음
            if ":memory:" not in url:
                cur.execute("PRAGMA journal_mode=WAL")     # 읽기와 쓰기 동시 진행(동시 사용자·워커 여럿일 때)
                cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=10000")       # 잠겨 있으면 10초까지 기다렸다가 쓰기
            cur.close()
    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 이전 버전 DB에 없는 컬럼을 추가한다(create_all은 기존 테이블을 바꾸지 않음). 큰 구조 변경은 Alembic 도입 권장.
ADDED_COLUMNS = [
    ("analysis_requests", "claim_token_hash", "VARCHAR(64)"),
    ("analysis_requests", "notices_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("recommendation_results", "empty_reason", "TEXT"),
    ("analysis_requests", "cogs_json", "TEXT"),
    ("action_items", "is_done", "BOOLEAN NOT NULL DEFAULT FALSE"),   # FALSE: SQLite(3.23+)·PostgreSQL·MySQL 모두 허용
    ("recommendation_results", "n_low_score", "INTEGER NOT NULL DEFAULT 0"),
    ("action_reports", "policy_ctx_json", "TEXT"),
    ("analysis_requests", "excluded_json", "TEXT"),
    ("saved_reports", "device_key_hash", "VARCHAR(64)"),              # 0.2: 로그인 대신 브라우저로 저장
]
# NOT NULL → NULL 허용으로 바뀐 컬럼. 지역에 같은 업종이 없으면 입지 위험이 정의되지 않음 / 0.2부터 저장 리포트는 계정이 없음.
# SQLite는 테이블을 지금 모델 정의로 다시 만들므로 saved_reports의 (브라우저, 리포트) 중복 방지 제약·색인도 이때 생긴다
RELAXED_NOT_NULL = {"risk_assessments": ["location_risk_pct", "location_risk_level"], "saved_reports": ["user_id"]}


def _rebuild_sqlite_table(eng, table: str, cols: list[str]) -> bool:
    """SQLite는 컬럼 제약을 ALTER로 못 바꾸므로 공식 절차(https://sqlite.org/lang_altertable.html#otheralter)대로
    새 정의로 테이블을 만들고 행을 옮긴 뒤 이름을 바꾼다. FK 검사는 잠시 끄고, 끝나면 foreign_key_check로 확인.
    워커 여러 개가 동시에 시작해도 한 번만 하도록 쓰기 잠금(BEGIN IMMEDIATE)을 잡은 뒤 다시 확인한다."""
    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateIndex, CreateTable
    from . import models  # noqa: F401  (테이블 정의를 Base.metadata에 등록)
    t = Base.metadata.tables[table]
    ddl = str(CreateTable(t).compile(eng))              # 현재 모델 정의(외래키 포함) 그대로, 이름만 임시로
    head = f"CREATE TABLE {table} ("
    if head not in ddl:
        raise RuntimeError(f"{table} DDL을 만들 수 없어요")
    ddl = ddl.replace(head, f"CREATE TABLE _new_{table} (", 1)
    old_cols = {c["name"] for c in inspect(eng).get_columns(table)}
    copy_cols = ", ".join(c.name for c in t.columns if c.name in old_cols)
    raw = eng.raw_connection()
    try:
        dbapi = raw.driver_connection
        iso = dbapi.isolation_level
        dbapi.isolation_level = None                    # 자동 커밋: PRAGMA foreign_keys는 트랜잭션 밖에서만 적용됨
        cur = dbapi.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        try:
            cur.execute("BEGIN IMMEDIATE")
            notnull = {r[1]: r[3] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
            if not any(notnull.get(c) for c in cols):        # 다른 워커가 이미 끝냄
                cur.execute("COMMIT")
                return False
            n_bad = len(cur.execute("PRAGMA foreign_key_check").fetchall())   # 원래 있던 불일치는 그대로 둔다(늘면 실패)
            seq = None                                  # AUTOINCREMENT 번호(지운 번호를 다시 쓰지 않게) — 새 테이블로 이어받는다
            if cur.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                row = cur.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (table,)).fetchone()
                seq = row[0] if row else None
            cur.execute(ddl)
            cur.execute(f"INSERT INTO _new_{table} ({copy_cols}) SELECT {copy_cols} FROM {table}")
            cur.execute(f"DROP TABLE {table}")
            cur.execute(f"ALTER TABLE _new_{table} RENAME TO {table}")
            if seq is not None and "AUTOINCREMENT" in ddl.upper():
                if cur.execute("SELECT 1 FROM sqlite_sequence WHERE name=?", (table,)).fetchone():
                    cur.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (seq, table))
                else:                                   # 옮긴 행이 없으면 번호 기록이 없다 → 옛 번호부터 이어 가게 만든다
                    cur.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, seq))
            for ix in t.indexes:
                cur.execute(str(CreateIndex(ix).compile(eng)))
            bad = cur.execute("PRAGMA foreign_key_check").fetchall()
            if len(bad) > n_bad:
                raise RuntimeError(f"{table} 재작성 후 FK 불일치가 늘었어요: {bad[:3]}")
            cur.execute("COMMIT")
            return True
        except Exception:
            if dbapi.in_transaction:
                cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys=ON")
            dbapi.isolation_level = iso
    finally:
        raw.close()


# 이전 DB에 새로 만들어야 하는 색인·중복 방지 제약(모델 정의 그대로). SQLite는 테이블 재작성 때 함께 생기고,
# PostgreSQL·MySQL은 여기서 없는 것만 만든다(중복 방지 제약은 같은 이름의 UNIQUE 색인으로)
ENSURED_INDEXES = {"saved_reports": ["ix_saved_reports_device_key_hash", "uq_saved_reports_device_report"]}


def _ensure_indexes(eng, table: str, names: list[str]) -> list[str]:
    from sqlalchemy import UniqueConstraint, inspect, text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.schema import CreateIndex
    insp = inspect(eng)
    have = {i["name"] for i in insp.get_indexes(table)} | {u["name"] for u in insp.get_unique_constraints(table)}
    t = Base.metadata.tables[table]
    made = []
    for name in names:
        if name in have:
            continue
        ix = next((i for i in t.indexes if i.name == name), None)
        if ix is not None:
            stmt = CreateIndex(ix)
        else:                                    # 중복 방지 제약은 같은 이름의 UNIQUE 색인으로(모델 메타데이터는 건드리지 않게 SQL로)
            uc = next(c for c in t.constraints if isinstance(c, UniqueConstraint) and c.name == name)
            stmt = text(f"CREATE UNIQUE INDEX {name} ON {table} ({', '.join(c.name for c in uc.columns)})")
        try:
            with eng.begin() as conn:
                conn.execute(stmt)
            made.append(f"{table} 색인 {name}")
        except DBAPIError as e:                  # 동시에 시작한 다른 워커가 먼저 만들었으면 괜찮다 — 다시 조회해 확인
            fresh = inspect(eng)
            if name not in {i["name"] for i in fresh.get_indexes(table)} | {u["name"] for u in fresh.get_unique_constraints(table)}:
                raise RuntimeError(f"{table} 색인 {name}을 만들지 못했어요(중복 데이터 등): {e.orig}") from e
    return made


def migrate(eng=None):
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import DBAPIError
    from . import models  # noqa: F401  (테이블 정의를 Base.metadata에 등록 — 모델을 아직 안 읽은 스크립트에서 불러도 되게)
    eng = eng or engine
    insp = inspect(eng)
    tables = set(insp.get_table_names())
    added = []
    for table, col, ddl in ADDED_COLUMNS:
        if table in tables and col not in {c["name"] for c in insp.get_columns(table)}:
            try:
                with eng.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                added.append(f"{table}.{col}")
            except DBAPIError:                       # 동시에 시작한 다른 워커가 먼저 추가했으면 괜찮다 — 다시 조회해 확인
                if col not in {c["name"] for c in inspect(eng).get_columns(table)}:
                    raise
    for table, cols in RELAXED_NOT_NULL.items():
        if table not in tables:
            continue
        info = {c["name"]: c for c in inspect(eng).get_columns(table)}
        todo = [c for c in cols if c in info and not info[c]["nullable"]]
        if not todo:
            continue
        if eng.dialect.name == "sqlite":
            if not _rebuild_sqlite_table(eng, table, todo):
                continue
        else:
            t = Base.metadata.tables[table]
            with eng.begin() as conn:
                for c in todo:
                    if eng.dialect.name in ("mysql", "mariadb"):     # MySQL은 DROP NOT NULL이 없어 형식을 다시 적는다
                        conn.execute(text(f"ALTER TABLE {table} MODIFY {c} {t.c[c].type.compile(dialect=eng.dialect)} NULL"))
                    else:
                        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {c} DROP NOT NULL"))
        added += [f"{table}.{c} (NULL 허용)" for c in todo]
    for table, names in ENSURED_INDEXES.items():
        if table in tables:
            added += _ensure_indexes(eng, table, names)
    return added
