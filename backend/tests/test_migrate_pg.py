"""PostgreSQL에서 0.1 DB(로그인 시절) → 0.2 자동 변환. PostgreSQL이 있을 때만 돈다:
MIRI_TEST_PG_URL=postgresql+psycopg://user@host:port/빈_DB  (드라이버: pip install "psycopg[binary]")"""
import os
import pytest

PG = os.environ.get("MIRI_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="MIRI_TEST_PG_URL이 없으면 건너뜀(PostgreSQL 전용)")


def test_pg_migrates_old_saved_reports():
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError
    from app.db import Base, make_engine, migrate
    from app import models  # noqa: F401
    eng = make_engine(PG)
    try:
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
        with eng.begin() as c:                                     # 0.1 모양으로 되돌린다
            c.execute(text("ALTER TABLE saved_reports DROP CONSTRAINT uq_saved_reports_device_report"))
            c.execute(text("DROP INDEX ix_saved_reports_device_key_hash"))
            c.execute(text("ALTER TABLE saved_reports DROP COLUMN device_key_hash"))
            c.execute(text("ALTER TABLE saved_reports ALTER COLUMN user_id SET NOT NULL"))
            c.execute(text("ALTER TABLE saved_reports ADD CONSTRAINT saved_reports_user_id_report_id_key UNIQUE (user_id, report_id)"))
            c.execute(text("INSERT INTO users (user_id, email, password_hash, name, role, created_at) "
                           "VALUES (1, 'old@example.com', 'x', '', 'OWNER', now())"))
            c.execute(text("INSERT INTO commercial_areas (area_id, area_code, area_name, area_level, province) "
                           "VALUES (1, '11680', '강남구', 'district', '서울특별시')"))
            c.execute(text("INSERT INTO business_categories (category_id, category_code, category_name, parent_category, has_sales_data) "
                           "VALUES (1, 'CS100010', '커피-음료', '외식업', true)"))
            c.execute(text("INSERT INTO analysis_requests (request_id, public_id, user_id, main_area_id, budget, monthly_rent_limit, "
                           "labor_cost, initial_investment, business_goal, user_type, other_fixed, loan_amount, loan_rate_annual, "
                           "owner_salary, licenses_json, categories_json, data_quarter, model_version, notices_json, created_at) "
                           "VALUES (1, 'a1', 1, 1, 1, 1, 1, 0, '기본', 'OWNER', 0, 0, 0, 0, '[]', '[]', 20252, 'v', '[]', now())"))
            c.execute(text("INSERT INTO action_reports (report_id, public_id, request_id, category_id, one_line_summary, created_at) "
                           "VALUES (1, 'r1', 1, 1, 'x', now())"))
            c.execute(text("INSERT INTO saved_reports (user_id, report_id, memo, created_at) VALUES (1, 1, '옛 메모', now())"))
        done = migrate(eng)
        assert set(done) == {"saved_reports.device_key_hash", "saved_reports.user_id (NULL 허용)",
                             "saved_reports 색인 ix_saved_reports_device_key_hash",
                             "saved_reports 색인 uq_saved_reports_device_report"}, done
        cols = {c["name"]: c for c in inspect(eng).get_columns("saved_reports")}
        assert cols["user_id"]["nullable"] and "device_key_hash" in cols
        with eng.begin() as c:
            assert c.execute(text("SELECT user_id, memo, device_key_hash FROM saved_reports")).all() == [(1, "옛 메모", None)]
            c.execute(text("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h1', 1, now())"))
            c.execute(text("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h2', 1, now())"))
        with pytest.raises(IntegrityError):                           # 같은 브라우저·같은 리포트는 한 번
            with eng.begin() as c:
                c.execute(text("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('h1', 1, now())"))
        assert migrate(eng) == []                                      # 두 번째 실행은 할 일 없음
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


def test_pg_duplicate_rows_stop_migration_loudly():
    """중복 저장이 이미 있으면 중복 방지 색인을 만들 수 없다 — 조용히 넘어가지 않고 이유와 함께 멈춘다."""
    from sqlalchemy import text
    from app.db import Base, make_engine, migrate
    from app import models  # noqa: F401
    eng = make_engine(PG)
    try:
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
        with eng.begin() as c:
            c.execute(text("ALTER TABLE saved_reports DROP CONSTRAINT uq_saved_reports_device_report"))
            c.execute(text("INSERT INTO commercial_areas (area_id, area_code, area_name, area_level, province) "
                           "VALUES (1, '11680', '강남구', 'district', '서울특별시')"))
            c.execute(text("INSERT INTO business_categories (category_id, category_code, category_name, parent_category, has_sales_data) "
                           "VALUES (1, 'CS100010', '커피-음료', '외식업', true)"))
            c.execute(text("INSERT INTO analysis_requests (request_id, public_id, main_area_id, budget, monthly_rent_limit, "
                           "labor_cost, initial_investment, business_goal, user_type, other_fixed, loan_amount, loan_rate_annual, "
                           "owner_salary, licenses_json, categories_json, data_quarter, model_version, notices_json, created_at) "
                           "VALUES (1, 'a1', 1, 1, 1, 1, 0, '기본', 'OWNER', 0, 0, 0, 0, '[]', '[]', 20252, 'v', '[]', now())"))
            c.execute(text("INSERT INTO action_reports (report_id, public_id, request_id, category_id, one_line_summary, created_at) "
                           "VALUES (1, 'r1', 1, 1, 'x', now())"))
            for _ in range(2):
                c.execute(text("INSERT INTO saved_reports (device_key_hash, report_id, created_at) VALUES ('hA', 1, now())"))
        with pytest.raises(RuntimeError, match="uq_saved_reports_device_report"):
            migrate(eng)
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()
