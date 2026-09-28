# MIRI 한 컨테이너 이미지: ① Node로 프론트 빌드 → ② Python 이미지에 백엔드 + 프론트 빌드(dist) + 원천 CSV + 미리 만든 DB
#   docker build -t miri .
#   docker run --rm -p 8000:8000 -e PORT=8000 miri      → http://localhost:8000/
# Render 무료 플랜은 디스크가 재시작마다 이미지 상태로 돌아가므로 DB(SQLite)는 빌드 때 init_data.py로 만들어 넣는다.
# 비밀값(MIRI_ADMIN_KEY, KAKAO_REST_API_KEY)은 이미지에 넣지 않고 실행 환경변수로만 받는다.

# ---------- ① 프론트엔드 빌드 → /app/frontend/dist ----------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- ② 실행 이미지 ----------
FROM python:3.12-slim
# FORWARDED_ALLOW_IPS: Render 프록시가 붙이는 X-Forwarded-Proto를 믿어 리다이렉트가 https로 나가게(Render에선 요청이 프록시를 거쳐서만 들어옴)
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FORWARDED_ALLOW_IPS=* \
    MIRI_DATABASE_URL=sqlite:////app/data/miri.db \
    MIRI_DATA_DIR=/app/data_raw \
    MIRI_FRONTEND_DIST=/app/frontend/dist

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# 코드·CSV·화면은 root 소유(읽기 전용), 실행 사용자는 DB 폴더(/app/data)에만 쓸 수 있다(SQLite WAL 파일도 여기 생김)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin miri \
 && mkdir -p /app/data && chown miri:miri /app/data
COPY backend/ ./
COPY data_raw/ /app/data_raw/
# 첫 요청·기동을 빠르게(무료 플랜 CPU가 작음)
RUN python -m compileall -q /app/backend

USER miri
# 원천 적재 + 모델 학습 → /app/data/miri.db (약 10초). init_data.py는 실패한 CSV가 있어도 끝까지 가므로
# 적재 로그에 실패가 하나라도 있으면 빌드를 멈춘다(빠진 데이터로 배포되지 않게)
RUN python scripts/init_data.py \
 && python -c "import sqlite3, sys; n = sqlite3.connect('/app/data/miri.db').execute(\"SELECT COUNT(*) FROM data_ingestion_logs WHERE status != 'SUCCESS'\").fetchone()[0]; sys.exit(f'원천 적재 실패 {n}건 — 위 [FAIL] 줄을 확인하세요' if n else 0)"

# 화면은 DB와 상관없으므로 마지막에(프론트만 바뀌면 위의 DB 만들기를 다시 하지 않음)
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Render는 $PORT(기본 10000)를 준다. 무료 플랜 메모리(512MB)에 맞춰 워커 1개
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-10000}\" --workers 1"]
