"""0.1(로그인 시절) 계정 정보 정리(선택). 0.2부터 로그인이 없어 옛 계정·회원 분석·계정 저장 목록은 주인도 볼 수 없다.
이 스크립트는 그 데이터(이메일·이름·비밀번호 해시 포함)를 지운다. 되돌릴 수 없으니 먼저 miri.db를 백업하고,
큰 DB는 지우는 동안(수십 초) 쓰기가 막히므로 서버를 멈춘 뒤 실행하세요.

사용:  python scripts/purge_accounts.py         # 지울 개수만 보여 줌(DB를 바꾸지 않음)
       python scripts/purge_accounts.py --yes   # 실제로 지움
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import inspect
from app.db import SessionLocal, engine
from app.services.maintenance import purge_legacy_accounts
from app.settings import settings

ap = argparse.ArgumentParser()
ap.add_argument("--yes", action="store_true", help="실제로 지운다(없으면 개수만 보여 줌)")
a = ap.parse_args()
print(f"DB: {settings.database_url}")
if settings.database_url.startswith("sqlite:///") and not Path(settings.database_url[len("sqlite:///"):]).exists():
    sys.exit("DB 파일이 없어요 — DB 경로(MIRI_DATABASE_URL)를 확인하세요")      # 없는 경로에 빈 DB를 만들지 않게
if not {"users", "analysis_requests", "saved_reports"} <= set(inspect(engine).get_table_names()):
    sys.exit("MIRI 테이블이 없어요 — DB 경로(MIRI_DATABASE_URL)를 확인하세요")
with SessionLocal() as db:
    n = purge_legacy_accounts(db, apply=a.yes)
print(f"0.1 계정 {n['users']}개 · 계정이 만든 분석 {n['member_analyses']}건(딸린 리포트 포함) · 계정 저장 목록 {n['member_saved']}건 · "
      f"비회원 소유 확인 해시 {n['claim_hashes']}건")
print("→ 지웠어요." if a.yes else "→ 지우지 않았어요. 지우려면 서버를 멈추고 --yes 를 붙여 다시 실행하세요(되돌릴 수 없으니 miri.db 백업 먼저).")
