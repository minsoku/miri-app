"""초기 데이터 구축: 테이블 생성 → 원천 적재(UC-07) → 특징·모델 배치.

사용:  python scripts/init_data.py                # data_raw/ 기준 전체
       python scripts/init_data.py --skip-ingest  # 적재는 두고 모델만 재학습
"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import Base, engine, SessionLocal, migrate
from app.settings import settings
from app.services.ingest import run_ingestion
from app.services.features_batch import build_features

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", default=str(settings.data_dir))
ap.add_argument("--skip-ingest", action="store_true")
ap.add_argument("--metrics", default=None, help="백테스트 결과 JSON(선택) → scoring_model_versions.metrics_json")
a = ap.parse_args()

t = time.time()
Base.metadata.create_all(engine)
for col in migrate(engine):
    print(f"  DB 컬럼 추가(이전 버전 DB 호환): {col}")
print(f"DB: {settings.database_url}")
with SessionLocal() as db:
    if not a.skip_ingest:
        print("[1/2] 원천 적재")
        res = run_ingestion(db, Path(a.data_dir))
        if any(r["status"] == "FAIL" for r in res):
            print("  ⚠ 실패한 파일이 있습니다. data_ingestion_logs를 확인하세요.")
    print("[2/2] 특징·모델 배치")
    metrics = json.loads(Path(a.metrics).read_text(encoding="utf-8")) if a.metrics else None
    out = build_features(db, metrics=metrics)
print(f"완료 ({time.time() - t:.0f}초) · 모델 {out['model_version']} · 기준 분기 {out['base_quarter']}")
print("※ 서버가 켜져 있었다면 재시작하세요(MIRI_ADMIN_KEY를 지정한 서버는 X-Admin-Key 헤더로 "
      "POST /api/v1/admin/refresh?skip_ingest=true 를 호출해도 새 모델을 불러와요).")
