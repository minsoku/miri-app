# MIRI — 데이터 기반 상권 분석·업종 추천 서비스 (1차 구현)

초롱이팀 SW융합프로젝트. 기획·설계 보고서(2026-001 v1.0)의 스토리보드 **SB-01~09**를 구현했고(0.2에서 SB-01의 로그인은 뺐다), 분석 엔진은 **계산 로직 v2.1**(`miri_engine`, 명세서 0.1절에 v2.0 대비 변경 사항)을 사용한다.

**0.2 (2026-09-25) — 로그인 없음.** 회원가입·로그인을 없애 누구나 SB-01 시작 화면에서 바로 분석·저장까지 쓴다. 저장 리포트(SB-09)는 계정 대신 **브라우저마다** 따로 보관한다(브라우저가 만든 저장 키를 `X-Device-Key` 헤더로 보내고 서버는 해시만 저장). 여럿이 함께 쓰는 컴퓨터는 SB-09의 '이 브라우저의 저장 목록 모두 지우기'로 정리한다(로그아웃 대신). 0.1로 만든 DB는 서버 시작 시 자동 변환되고, 0.1의 회원 계정·회원 분석은 주인이 더는 로그인할 수 없어 열리지 않는다(지우려면 §5 `purge_accounts.py`).

| 구성 | 기술 | 위치 |
|---|---|---|
| 백엔드 API | Python · FastAPI · SQLAlchemy 2 (SQLite 기본, PostgreSQL/MySQL 전환 가능) | `backend/` |
| 분석 엔진 | 계산 로직 v2.1 (M-02 특징 · M-03 적합도 · M-04 위험도 · M-05 손익분기 · M-06 문장) | `backend/miri_engine/` |
| 프론트엔드 | React 18 · TypeScript · Vite, 모바일 우선 | `frontend/` |
| 원천 데이터 | 서울시 상권분석서비스 자치구 단위 8종 (2019Q1~2025Q2) | `data_raw/` |
| 문서 | API 명세 · ERD v2 · 화면 대응표 · DDL | `docs/` |

---

## 1. 빠르게 실행하기 (로컬)

필요: Python 3.10 이상, Node.js 18 이상.

```bash
# ① 백엔드: 패키지 설치 → DB 만들기(원천 적재 + 모델 학습, 약 10초) → 서버 실행
cd backend
python -m venv .venv
# macOS/Linux: source .venv/bin/activate      Windows(PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/init_data.py                  # miri.db 생성
uvicorn app.main:app --reload --port 8000    # API 문서: http://localhost:8000/docs

# ② 프론트엔드 (다른 터미널)
cd frontend
npm install
npm run dev                                  # http://localhost:5173  (/api 요청은 8000으로 프록시)
```

한 서버로 보여줄 때는 `cd frontend && npm run build` 후 백엔드만 실행하면 `http://localhost:8000/` 에서 화면까지 뜬다(`frontend/dist`를 자동 제공).

**서버 없는 데모**: `docs/demo/miri-demo.html` 파일을 브라우저로 열면 전체 흐름이 동작한다. 백엔드와 같은 계산 규칙을 브라우저 안에서 실행하며, 무작위 케이스 비교(기본 80건 분석 → 비교 약 1,200건, 확장 300건 → 약 4,000건)에서 불일치 0건을 확인했다(§4). 다시 만들려면 `npm run build:demo`.

로그인·비밀키 설정은 없다. 관리자 API(`/admin/*`, 데이터 갱신)를 서버 실행 중에 쓰려면 `MIRI_ADMIN_KEY`만 지정한다(§5·§6).

## 2. 화면 흐름 (보고서 6.2.3 사용자 이용 플로우)

| 스토리보드 | 화면 | 경로 | 주요 API |
|---|---|---|---|
| SB-01 | 시작 (사용자 유형 선택 · 로그인 없음) | `#/` | (선택만 — 유형은 분석 요청의 `user_type`으로 지원사업 매칭에 쓰임) |
| SB-02 | 상권 선택 (검색·지도·반경·후보) | `#/area` | `GET /places/search`, `/areas/candidates`, `/areas/map` |
| SB-03 | 창업 조건 입력 | `#/conditions` | (입력만) |
| SB-04 | 관심 업종 선택 | `#/interests` | `POST /analyses` |
| SB-05 | 추천 결과 TOP 5 | `#/analysis/:id` | `GET /analyses/{id}` |
| SB-06 | 폐업 위험도 (v2: 요인 효과 %, 두 축, 참고 지표) | `#/analysis/:id/risk/:code` | `GET /analyses/{id}/risk/{code}` |
| SB-07 | 손익분기점 (v2: 26일·카드수수료·달성배율) | `#/analysis/:id/breakeven/:code` | `POST /analyses/{id}/breakeven` |
| SB-08 | 액션 리포트 | `#/report/:rid` | `POST /analyses/{id}/reports`, `GET /reports/{rid}` |
| SB-09 | 저장 리포트 (이 브라우저의 목록) | `#/reports` | `POST·GET /me/reports`, `PATCH·DELETE /me/reports/{id}`, `POST /me/reports/clear` (`X-Device-Key` 헤더) |

화면별 상세·스크린샷은 [`docs/SCREENS.md`](docs/SCREENS.md), API는 [`docs/API.md`](docs/API.md), DB는 [`docs/ERD_v2.md`](docs/ERD_v2.md).

## 3. 폴더 구조

```
backend/
  app/
    main.py            FastAPI 앱(라우터 등록, 프론트 빌드 제공)
    models.py          DB 27개 테이블 = 보고서 6.3 ERD + 계산로직 v2 §9 변경분([v2] 표시)
    schemas.py         요청/응답 스키마 (= API 명세, /docs 자동 생성)
    routers/           meta · areas · analyses · reports · admin
    deps.py            브라우저 저장 키(X-Device-Key) 확인 · 관리자 키(X-Admin-Key) 확인
    services/
      ingest.py        UC-07 원천 적재 + 검증 + 수집 로그
      features_batch.py 분기 배치: DB 원천 → 특징 → 모델 학습 → area_category_features
      engine.py        API 런타임 엔진 상태(활성 모델 + 최신 분기 특징 메모리 적재)
      areas.py         지명 검색(로컬 사전 + 카카오 선택), 반경 후보, 지도, 상권 비교(UC-02)
      analysis.py      UC-01 추천 실행·저장
      risk_svc.py      UC-03 위험도 상세
      breakeven_svc.py UC-04 손익분기
      report_svc.py    UC-05 액션 리포트 · UC-06 저장/조회(브라우저별)
      maintenance.py   운영 정리(0.1 계정 정보 지우기 — scripts/purge_accounts.py)
      narrative.py     M-06 화면 문장 템플릿(한국어 조사 처리 포함)
      geo.py           경계 폴리곤 계산(포함·거리·단순화)
    seed/              자치구 경계, 지명 사전, 정책 지원 시드
  miri_engine/         계산 로직 v2 (명세서 그대로)
  scripts/             init_data · export_docs · export_demo_snapshot · parity_cases · purge_accounts(0.1 계정 정리, 선택)
  tests/               엔진 31 + API 39 + 문구 34 + 마이그레이션 6(PostgreSQL 2건은 MIRI_TEST_PG_URL이 있을 때만) + 검수 회귀(5·7~21·23차) 154 = 264개
frontend/
  src/screens/         SB-01~09 화면
  src/api/             API 클라이언트(http) + 데모 엔진(demo/)
  scripts/             inline(단일 HTML) · parity(데모↔백엔드 동일성)
e2e/                   flow(전체 흐름·스크린샷) · a11y(axe, WCAG 2.1 AA) · responsive(320~1280px) · monkey(무작위 UI)
                       · fuzz_api(API 퍼징) · load(동시 사용자)
docs/                  API.md · ERD_v2.md · SCREENS.md · openapi.json · schema_*.sql · demo/
data_raw/              원천 CSV
```

## 4. 테스트

저장소 루트에서 차례로 실행한다.

```bash
(cd backend && python -m pytest)                                  # 262 passed, 2 skipped(PostgreSQL 없을 때) — 실데이터 적재·학습 포함 약 3~4분
# 서버를 켠 상태에서: 전체 흐름 + 화면 캡처 (pip install playwright && playwright install chromium)
python e2e/flow.py http://127.0.0.1:8000/ e2e/shots
python e2e/flow.py "file://$PWD/docs/demo/miri-demo.html" e2e/shots_demo   # 서버 없는 데모도 같은 흐름
# 데모 엔진이 백엔드와 같은 결과를 내는지 (케이스 생성 → 비교)
(cd backend && python scripts/parity_cases.py ../frontend/.parity_cases.json 80)
(cd frontend && npm run parity)                                   # "비교 …건 · 불일치 0건"
# 품질 점검 도구(서버 실행 중, 데모는 BASE_URL 자리에 file://…/miri-demo.html)
python e2e/a11y.py http://127.0.0.1:8000/                         # 접근성 위반 0건이어야 통과
python e2e/responsive.py http://127.0.0.1:8000/ e2e/resp          # 320~1280px 가로 넘침·잘림
python e2e/monkey.py http://127.0.0.1:8000/ 250 1 e2e/monkey      # 무작위 UI 250단계: 예외·5xx·빈 화면
python e2e/fuzz_api.py http://127.0.0.1:8000 3000 1               # API 퍼징: 5xx·오류 형식·응답 불변식·브라우저별 저장 목록 분리
python e2e/load.py http://127.0.0.1:8000 30 3                     # 동시 30명 × 3라운드
```

검증 범위: DB 경로로 학습한 모델이 명세서 백테스트 모델과 계수·점수까지 동일(`test_db_trained_model_matches_csv_engine`), 로그인 없이 저장 목록을 브라우저(저장 키)마다 분리(다른 브라우저의 목록·삭제·메모는 404, 리포트 자체는 링크를 아는 누구나), 0.1 회원 분석은 계속 비공개(404), 0.1 DB의 저장 목록 테이블 자동 변환(행·번호 유지), 고정비 0원 같은 경계값, 입력 검증 한국어 메시지, 적재 실패 시 다른 파일 계속 진행 등. 작업 과정을 공유하지 않은 별도 검토 에이전트가 26차례(시연 리허설·교수 질문·회귀·API·문구·화면·접근성·처음 쓰는 사용자 관점·로그인 제거) 독립 검수했고, 지적 사항은 모두 수정한 뒤 차수별 회귀 테스트(`tests/test_round*.py`)와 parity 경로(`scripts/parity_cases.py`)를 추가했다. 마지막 검수 기준: 백엔드↔데모 동일성 매 차수 약 4,000건 불일치 0, 접근성 위반 0, 320~1280px 넘침 0, 무작위 UI·API 퍼징 문제 0.

## 5. 데이터 갱신 (UC-07)

1. 서울 열린데이터광장에서 새 분기 CSV를 받아 `data_raw/`의 같은 파일명으로 교체
2. `python scripts/init_data.py` (또는 서버 실행 중이면 관리자 키로 `POST /api/v1/admin/refresh` — 아래 '관리자 API')
3. 파일별 성공/실패는 `data_ingestion_logs`에 남고, 실패한 원천이 있으면 화면에 "이전 데이터로 분석했어요" 안내가 뜬다.
4. 서버가 켜져 있는 동안 CLI로 갱신했다면 서버를 재시작하거나 관리자 키로 `POST /api/v1/admin/refresh?skip_ingest=true`를 불러 새 모델을 올린다.
5. 코드를 새 버전으로 받았을 때 DB에 없는 컬럼은 서버 시작·`init_data.py` 실행 시 자동으로 추가된다(`app/db.py` `migrate`). 0.1 → 0.2(로그인 제거) 변환은 SQLite와 PostgreSQL 16에서 확인했다(`tests/test_migrate.py`, PostgreSQL은 `MIRI_TEST_PG_URL`을 주면 `tests/test_migrate_pg.py`). MySQL도 같은 절차를 SQL로 실행하지만 실DB로는 시험하지 않았다. 테이블 구조가 크게 바뀌면 `miri.db`를 지우고 `init_data.py`를 다시 돌리면 된다.
6. (선택) 0.1 계정 정보 정리: 로그인이 없어 옛 계정(이메일·이름·비밀번호 해시)·회원 분석·계정 저장 목록은 주인도 볼 수 없다. `python scripts/purge_accounts.py`로 개수만 확인하고(DB를 바꾸지 않음), **서버를 멈춘 뒤** `--yes`를 붙이면 지운다(되돌릴 수 없으니 `miri.db` 백업 먼저. 계정 5천 개·분석 1만 건 규모에서 약 1분 걸리고 그동안 쓰기가 막힌다).

관리자 API: 로그인이 없으므로 서버에 `MIRI_ADMIN_KEY`(32자 이상)를 지정하고 같은 값을 `X-Admin-Key` 헤더로 보낸다. 지정하지 않은 서버는 관리자 API가 꺼져 있다(403 `ADMIN_DISABLED`).

```bash
curl -X POST -H "X-Admin-Key: $MIRI_ADMIN_KEY" "http://localhost:8000/api/v1/admin/refresh?skip_ingest=true"
```

## 6. 설정 (환경변수)

`backend/.env` 파일이 있으면 자동으로 읽는다(`.env.example` 참고, 이미 설정된 환경변수가 우선). 상대 경로는 `backend/` 기준.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MIRI_ADMIN_KEY` | (없음 → 관리자 API 꺼짐) | 관리자 API(`/admin/*`) 키, 32자 이상. `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `MIRI_DATABASE_URL` | `backend/miri.db` (= `sqlite:///miri.db`) | PostgreSQL 예: `postgresql+psycopg://user:pw@host/miri` (드라이버 별도 설치) |
| `MIRI_DATA_DIR` | `data_raw/` | 원천 CSV 폴더 |
| `MIRI_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 쉼표 구분 |
| `MIRI_FRONTEND_DIST` | `frontend/dist` | 백엔드가 함께 제공할 프론트 빌드 폴더 |
| `KAKAO_REST_API_KEY` | (없음) | 넣으면 장소 검색에 카카오 로컬 API 결과 추가 |

## 7. 알고 있는 한계와 다음 단계

| 항목 | 현재 | 다음 단계 |
|---|---|---|
| 분석 단위 | **자치구**(25개). 반경은 '반경에 걸친 자치구 후보'를 고르는 데 쓰이고, 화면에 보정 분석 안내 표시(보고서 예외 흐름) | 상권 단위 CSV(OA-15577 등) 적재 → `area_level='trade_area'`로 같은 파이프라인 재학습. 로더는 이미 `level="trade_area"` 지원 |
| 지도 | 타일 없는 벡터 지도(자치구 경계 + 역 라벨). 오프라인·데모에서도 동작 | 카카오맵으로 바꿀 때는 `frontend/src/components/SeoulMap.tsx`만 교체 |
| 지명 검색 | 역·거리 147곳 + 자치구 25곳 로컬 사전(좌표는 근사, ‘망원동’처럼 동 이름은 ‘망원’으로 한 번 더 찾고, 강남녁·선능역 같은 소리 오타, ‘서울 강남구’·‘관악구 신림동’·‘마포 연남동’·‘강남역 2번 출구’ 같은 주소식 입력도 찾음 — 구 이름이 있으면 그 구 안에서만) | `KAKAO_REST_API_KEY` 설정 시 카카오 검색 병행 |
| 비용 적합도(F) | 외식업만 공식 원가율(40.7%)이 있어, 다른 대분류가 섞이면 순위에 미반영(화면에 안내) | 업종별 원가율 근거 확보 → `category_cost_profiles` |
| 정책 지원 | 실제 사업 7건 시드(금액·기간 미기재, 확인일 2026-09-20) | 기업마당 지원사업 API로 자동 갱신 |
| 창업 비용 | 업종별 창업비 데이터 없음 → 예산은 초기투자비 검증과 운영자금 체크리스트에만 사용 | 프랜차이즈 정보공개서 등 창업비 데이터 연계 |
| 저장 리포트 | 로그인 없이 **브라우저마다** 보관(다른 기기와 공유되지 않고, 브라우저 데이터를 지우면 목록도 사라짐 — 리포트 자체는 링크로 계속 열림). 저장소를 막은 브라우저(사생활 보호 모드 등)는 새로고침하면 목록이 사라져 화면에 안내한다. 체크리스트 완료 표시는 리포트마다 하나라 링크를 받은 사람이 체크하면 함께 바뀐다 | 여러 기기에서 이어 쓰려면 계정 또는 '저장 목록 옮기기 코드' 추가 |
