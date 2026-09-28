# MIRI API 명세 (v0.2 · 계산 로직 v2.1 `risk-v2.1`)

- 기본 주소: `http://localhost:8000/api/v1` · 대화형 문서: `http://localhost:8000/docs` · 기계용: [`openapi.json`](openapi.json)
- 형식: JSON(UTF-8). **금액은 모두 원(KRW) 정수**, 비율은 0~1 소수(예: 0.161 = 16.1%).
- **로그인 없음**(0.2): 회원가입·로그인이 없고 누구나 분석·위험도·손익분기·리포트·저장을 쓴다.
- 접근 규칙: 분석·리포트는 추측 불가 ID(UUID)를 아는 사람이면 누구나 연다(링크 공유). 이전 버전에서 회원이 만든 분석·리포트는 주인이 더는 로그인할 수 없어 404로 숨긴다.
- 저장 리포트(🔑): 계정 대신 **브라우저 저장 키**로 구분한다. 화면이 리포트·저장 목록을 처음 부를 때 브라우저가 임의의 키(32바이트 → base64url 43자, 영문·숫자·`-`·`_` 32~128자 허용)를 만들어 localStorage에 두고 리포트·저장 목록 요청에 `X-Device-Key` 헤더로 보낸다. 서버는 키의 SHA-256만 저장한다. 키가 없으면 400 `DEVICE_KEY_REQUIRED`, 형식이 틀리면 400 `INVALID_DEVICE_KEY`. 다른 브라우저·기기에서는 목록이 보이지 않고, 브라우저 데이터를 지우면 목록도 사라진다(리포트 자체는 링크로 계속 열림).
- `GET /reports/{id}`·`POST /analyses/{id}/reports`에 `X-Device-Key`를 함께 보내면 `saved_report_id`에 이 브라우저의 저장 번호가 온다(저장하지 않았으면 `null`).

## 엔드포인트 한눈에

| 메서드 · 경로 | 화면 | 유스케이스 | 설명 |
|---|---|---|---|
| `GET /health` | – | – | 헬스 체크 |
| `GET /meta` | 공통 | – | 데이터 기준 분기, 모델 버전, 등급 기준(점수 컷·연 폐업률 경계), 목표별 가중치 |
| `GET /industries` | SB-04 | – | 업종 100개 + 관심 업종 칩 6개(코드 묶음). `recommendable`: 카드 매출이 있는 지역이 5곳 이상이라 추천 대상이 될 수 있는 업종(SB-03 보유 자격 칩은 이 업종들의 자격만) |
| `GET /places/search?q=` | SB-02 | – | 지명 검색(역·거리·자치구, 카카오 키가 있으면 카카오 결과 포함). 결과가 없으면 끝의 '동·길·로·거리·시장·역'을 떼고 이름이 그 말로 시작하거나 별칭과 같은 곳을 한 번 더(망원동 → 망원역, 상암동 → 디지털미디어시티역, 신촌역 → 신촌 연세로), 그래도 없으면 흔한 소리 오타를 고쳐 한 번 더(강남녁·잠실력 → 역, 선능 → 선릉, 끝 글자 첫소리가 ㅇ인 강남억 → 강남). 검색어는 50자까지(넘으면 422 "검색어가 너무 길어요") |
| `GET /areas/candidates?lat=&lng=&radius_m=` | SB-02 | UC-01 | 반경에 걸친 후보 지역 + 카드 지표(일평균 유동인구·점포 수·3.3㎡당 임대료) |
| `GET /areas/map` | SB-02 | – | 지도용 단순화 경계(GeoJSON) + 지명 라벨 |
| `GET /areas/{area_code}` | – | – | 지역 기본 지표 |
| `POST /areas/compare` | SB-02 '후보 N곳 비교' 시트 | UC-02 | 2~4개 지역을 같은 기준(최신 분기)으로 비교: 유동인구·점포 수·임대료·전 업종 평균 위험·위험 높은 업종 비율 + (업종 선택 시) 그 업종의 위험·입지 위험·점포당 매출 |
| `POST /analyses` | SB-03·04 → 05 | UC-01 | 분석 실행: 조건 저장(선택: 분야별 원가율 `cogs_rates`, 시작 화면에서 고른 사용자 유형 `user_type` — 지원사업 매칭에 쓰임) → 추천 TOP 5(적합도 20점 이상만 — 모자라면 적은 대로) · 관심 업종 · 주의 업종 |
| `GET /analyses/{id}` | SB-05 | UC-01 | 분석 결과 다시 보기 |
| `GET /analyses/{id}/risk/{code}?be=` | SB-06 | UC-03 | 폐업 위험도 상세(두 축·요인 효과·참고 지표·대안 입지). 리포트에서 열 때 `be`(그 리포트에 반영한 손익분기 id)를 주면 인근 지역 `alternatives[].affordable`을 그 비용으로 판단(`affordability_basis`: `report`, 아니면 `analysis`; 원가율을 모르면 `affordability_cogs_known`=false로 '평균 매출 ≥ 월 고정비'만 봄, 목표 월수입 포함 여부는 `affordability_owner_included`) |
| `POST /analyses/{id}/breakeven` | SB-07 | UC-04 | 손익분기(분석 조건이 기본값, 바꾼 값만 보내기) |
| `GET /analyses/{id}/breakeven/{break_even_id}` | SB-07·08 | UC-04 | 저장된 손익분기 결과 다시 보기(리포트에 반영한 계산을 그대로 열 때) |
| `POST /analyses/{id}/reports` | SB-08 | UC-05 | 액션 리포트 생성(한줄 결론·체크리스트·지원사업). 같은 분석·업종·손익분기 입력으로 이미 만든 리포트가 있으면 그것을 돌려준다(저장한 것 우선) |
| `GET /reports/{report_id}` | SB-08 | UC-05 | 리포트 조회 |
| `PATCH /reports/{report_id}/items/{action_id}` | SB-08·09 | UC-05·06 | 체크리스트 항목 완료 표시 `{"done": true}` — 다시 열어도 유지(리포트 링크를 아는 사람 누구나) |
| `POST /me/reports` 🔑 | SB-08·09 | UC-06 | 이 브라우저의 목록에 리포트 저장(메모 선택). 이미 저장했으면 메모만 바꾼다(SB-09 메모 쓰기·수정). 링크로 받은 리포트도 저장할 수 있다 |
| `GET /me/reports` 🔑 | SB-09 | UC-06 | 이 브라우저가 저장한 리포트 |
| `POST /me/reports/clear` 🔑 | SB-09 | UC-06 | 이 브라우저의 저장 목록 모두 지우기(여럿이 쓰는 컴퓨터 정리 — 로그아웃 대신) → `{"deleted": 지운 개수}`. 되돌릴 수 없어 따로 이름 붙인 주소로만 받는다(단건 삭제 주소를 잘못 쓴 `DELETE /me/reports`는 405). 리포트 자체는 링크로 계속 열림 |
| `PATCH /me/reports/{saved_report_id}` 🔑 | SB-09 | UC-06 | 메모 수정 `{"report_id", "memo"}` — `report_id`를 주면 그 리포트의 저장 항목일 때만, 지운 항목이면 404(다시 저장하지 않음) |
| `DELETE /me/reports/{saved_report_id}?report_id=` 🔑 | SB-09 | UC-06 | 저장 삭제(`report_id`를 주면 그 리포트의 저장 항목일 때만 — 지운 번호가 재사용돼도 다른 항목을 지우지 않게). 다른 브라우저의 저장 항목은 404 |
| `POST /admin/refresh` 🔒관리자 키 | – | UC-07 | 원천 재적재 + 특징·모델 배치 + 엔진 재로딩(다른 워커는 활성 모델이 바뀐 것을 10초 안에 알아채 스스로 다시 올림) |
| `GET /admin/ingestion-logs` 🔒관리자 키 | – | UC-07 | 수집 로그 |

🔑 = `X-Device-Key` 헤더(브라우저 저장 키) 필요. 🔒관리자 키 = 서버 환경변수 `MIRI_ADMIN_KEY`와 같은 값을 `X-Admin-Key` 헤더로(지정하지 않은 서버는 관리자 API가 꺼져 403 `ADMIN_DISABLED`).

## 오류 형식

모든 오류는 같은 모양이고 `message`는 화면에 그대로 띄울 수 있는 한국어다.

{{err_validation}}

| 코드 | HTTP | 뜻 |
|---|---|---|
| `VALIDATION_ERROR` | 422 | 입력 형식·범위 오류(`fields`에 항목별 메시지) |
| `INVALID_CONDITION` | 422 | 조건 모순(예: 초기 투자비 > 총 예산) |
| `UNKNOWN_AREA` / `UNKNOWN_INDUSTRY` / `UNKNOWN_LICENSE` | 404·422 | 없는 지역·업종 코드 / 업종 목록에 없는 자격 이름 |
| `OUT_OF_COVERAGE` | 422 | 서울 밖 위치 |
| `COGS_REQUIRED` · `TICKET_REQUIRED` · `VARIABLE_RATE_TOO_HIGH` | 422 | 손익분기 입력 보완 필요(`VARIABLE_RATE_TOO_HIGH`의 `fields[].value`에 계산에 쓴 원가율·기타 수수료) |
| `DEVICE_KEY_REQUIRED` · `INVALID_DEVICE_KEY` | 400 | 저장 리포트 요청에 브라우저 저장 키(`X-Device-Key`)가 없음 / 형식이 틀림 |
| `ANALYSIS_NOT_FOUND` · `REPORT_NOT_FOUND` · `BREAKEVEN_NOT_FOUND` · `SAVED_NOT_FOUND` | 404 | 없음(저장 항목은 다른 브라우저 것이어도 404) |
| `NO_AREA_DATA` · `NO_INDUSTRY_DATA` | 422·404 | 분석할 데이터가 전혀 없음 |
| `EMPTY_QUERY` · `NEED_MORE_AREAS` · `INVALID_INPUT` | 422 | 빈 검색어 / 비교 지역 1개 / 기타 입력 오류 |
| `FORBIDDEN` · `ADMIN_DISABLED` | 403 | 관리자 키가 틀림 / 서버에 `MIRI_ADMIN_KEY`가 없어 관리자 API가 꺼져 있음 |
| `ENGINE_NOT_READY` | 503 | 모델·특징 테이블이 비어 있음(`init_data.py` 필요) |
| `INTERNAL_ERROR` | 500 | 예상 못 한 오류(자세한 내용은 서버 로그에만) |

## 예시 (실제 호출 결과, 배열은 일부만)

### 지명 검색 `GET /places/search?q=강남`
{{search}}

### 후보 지역 `GET /areas/candidates?lat=37.4981&lng=127.028&radius_m=500&place_name=강남역`
{{candidates}}

### 분석 실행 `POST /analyses`
요청 (SB-03 입력 + SB-04 관심 업종. `categories`는 관심 업종과 같은 분야에서만 추천할 때):
{{analysis_in}}

응답 (TOP·관심·주의 목록은 1개씩만 표시):
{{analysis_out}}

필드 메모
- `suitability` = w_D·D + w_S·S + w_F·F (목표별 가중치 `weights`). `f_applied=false`면 F 없이 D·S로만 계산하고 `f_note`에 이유.
- `location_risk_pct`: 같은 업종끼리 비교한 입지 위험 백분위. 90 이상은 TOP에서 빼고 `cautions`로.
- `reason`(저장용 긴 근거), `reason_short`·`chips`·`cautions`(카드용), `peak`(시간대·요일 매출 쏠림).
- `missing_interests`: 이 지역에 최근 1년 점포가 없어 적합도를 못 낸 관심 업종(위험도는 서울 같은 업종 평균 조건으로 조회 가능).
- 월 고정비가 0원이면 손익분기 매출도 0원 → `achievability_ratio=null`, `cost_pressure="여유"`, 비용 적합도 F=100.
- `achievability_ratio`(평균 매출 ÷ 손익분기)는 **소수 둘째 자리 내림** 값이다(0.9996 → 0.99). 배지·문장·추천 제외(1 미만)는 모두 이 값으로 판정하므로 '1.00배인데 위험' 같은 표시가 생기지 않는다. 비용 적합도 F는 내림 전 값으로 계산.
- 추천 제외(`eligible=false`) 이유: 매출 데이터 없음 · 점포 부족(수요 미검증) · 카드 매출 데이터 부족(점포당 월 50만원 미만) · 매출을 비교할 지역이 적음(N곳) · 자격 필요 · 사용자 제외 · 대분류 제한 · 평균 매출이 월 고정비보다 적음 · 평균 매출로 손익분기 미달 · 원가·수수료가 매출의 100% 이상 · 점포당 매출이 서울 중간값의 X배(대형 점포 가능). 사용자가 뺀 업종(`excluded_industries`)은 분석 조건(`conditions.excluded_industries`)에 저장되고 리포트의 비슷한 업종 대안에도 쓰지 않는다. 목표 월수입을 넣은 분석은 '(목표 월수입 포함)'을 붙인다.
- `score_note`: 적합도를 못 내거나(매출 데이터 없음) 다른 업종과 같은 잣대가 아닐 때 이유. `area.scope_note`: 자치구 단위 분석 안내. `empty_reason`: TOP이 0개일 때 가장 큰 원인.
- `cogs_rates`(선택, 0~0.95): 넣은 분야는 비용 적합도 F와 손익분기 원가율 기본값에 쓰인다(외식업은 비우면 평균 40.7%, 서비스업·소매업은 비우면 F를 계산하지 않음). 모든 후보 분야의 원가율을 알면 `f_applied=true`.

### 위험도 `GET /analyses/{id}/risk/CS100010`
{{risk}}

- `factors[].effect_pct`: 그 요인 때문에 예상 폐업률이 몇 % 달라졌는지(`+` 위험↑, `−` 위험↓). v1의 `32/40점` 배점을 대체.
- `reference`: 위험 점수 계산에 쓰지 않는 참고 지표(화면에 '참고용' 표시).
- `recheck=true`(고위험)면 '창업 재검토 권장' 안내, `alternatives`는 같은 업종·입지 위험이 낮은 인근 지역(구 중심 7km 이내 + SB-02에서 후보로 보인 구, 종합 위험·예상 연 폐업률도 함께).
- 이 지역에 같은 업종 점포가 없으면 `fallback=true`: 서울 같은 업종 평균 조건으로 예측하고 `location_risk_pct`·`location_grade`는 `null`.
- 참고 지표의 '업종 전체(서울) 매출 전년 대비' 메모는 실제로 합산한 지역 수(올해·작년 모두 카드 매출을 믿을 수 있는 구)를 적는다. '폐업 점포 평균 영업 기간'은 구 전체·전 업종 값이다.

### 손익분기 `POST /analyses/{id}/breakeven`
요청(바꾼 값만):

{{be_in}}

응답:
{{be_out}}

- `composition`: SB-07 막대(고정비·변동비·목표이익). 목표이익 = 대표자 목표 월수입.
- 원가율 기본값: 요청의 `cogs_rate` → 분석 조건의 분야별 원가율(`inputs.cogs_source="analysis"`) → 업종 대분류 평균(외식업 40.7%, `"default"`). 셋 다 없으면 `COGS_REQUIRED`.
- 객단가 기본값(UC-04 대안 흐름): 요청의 `avg_ticket` → 이 지역 같은 업종 실제 평균(`inputs.ticket_source="local"`) → 서울 같은 업종 평균(`"seoul"`, 경고 문구에 표시). 셋 다 없을 때만 `TICKET_REQUIRED`.
- `cost_pressure`: 달성배율 1.0 미만 위험 · 1.15 미만 빠듯 · 1.3 미만 보통 · 그 이상 여유. `market_tx_ps_day`는 필요 결제 건수와 같은 '영업일' 기준(달력일 값 × 365/12 ÷ 26).
- 입력 객단가로 계산한 하루 필요 결제가 이 지역 점포 평균의 1.2배 이상이면 `warnings`에 알린다(매출 기준 달성배율만 보면 놓치는 경우). 배수는 올림 전 하루 결제 건수로 계산한다.
- `inputs.overridden`: 이 요청이 덮어쓴 항목. `inputs.changed`: 그중 기본값(분석 조건·조건 원가율·업종 평균·지역 평균 객단가)과 실제로 다른 항목 — 같은 값을 다시 넣었으면 '바꾼 값'이 아니다. `inputs.required`: 기본값이 없어 꼭 넣어야 했던 항목(원가율·객단가) — 저장된 계산을 다시 열 때 '분석 조건으로'가 무엇을 되돌릴지 정한다.

{{err_cogs}}

### 액션 리포트 `POST /analyses/{id}/reports`
{{report}}

- `break_even_id`를 안 보내면 분석 조건으로 손익분기를 새로 계산해 넣는다(원가율 기본값이 없는 업종은 `breakeven=null`).
- 한줄 결론 우선순위(명세서 11절): 지역 데이터 없음(서울 같은 업종 평균으로 대체) → 자격 필요(자격 요건부터, 적자면 함께) → 폐업 위험 높음·고위험(손익분기 미달·빠듯·양호별 문장, 입지 위험 90 이상·운영자금·데이터 단서, 대안 업종·인근 구) → 손익분기 미달('월 고정비를 X 이하로' — 그 한도가 목표 월수입보다 작으면 목표를 낮추라고) → 개설 조건(평균 매출 < 월 고정비·수요 미검증) → 입지 위험 매우 높음 → 진입 검토(+ '다만' 단서: 입지 위험 높음·운영자금 부족·초기 투자비 > 예산·데이터 적음).
- 대안 업종(같은 계열, 예상 폐업률 15% 이상 낮고 등급도 낮음)과 인근 구는 지금 비용(리포트에 반영한 원가율·수수료 포함)으로 평균 매출이 버틸 수 있을 때만 권한다. 손익분기를 못 냈거나 적자 구조·고위험이면 대출·보증 상품은 권하지 않는다.
- 체크리스트의 '월 고정비를 X 이하로'의 X는 표시 단위에서 내림한 한도이고, '월 Y 줄여야 함'은 화면에 보이는 두 금액의 차이다.
- 체크리스트 항목에는 `action_id`·`done`(완료 표시)이 있다. 업종 자체 폐업률이 높거나 지역 폐업 점포 수명이 짧으면 운영자금 기준을 12개월로 쓴다(운영자금 항목·한줄 결론의 운영비 단서도 같은 기준). 운영비는 임대료+인건비+기타 고정비+대출 이자로 계산한다.
- `breakeven.changed`: 반영한 손익분기에서 분석 조건과 다르게 바꾼 값(SB-08 '손익분기 화면에서 바꾼 값 기준' 줄).
- 같은 분석·업종에서 손익분기 입력값(계산에 쓴 값)이 같으면 새 리포트를 만들지 않고 기존 리포트를 돌려준다 — 저장한 리포트가 있으면 그것을.

### 상권 비교 `POST /areas/compare`
{{compare}}

### 저장 `POST /me/reports` 🔑 · 목록 `GET /me/reports` 🔑
요청 헤더: `X-Device-Key: <브라우저 저장 키>`

{{save}}
{{saved}}

- 목록 항목의 `required_monthly_sales`·`achievability_ratio`·`owner_included`·`edited`(바꾼 값 기준인지)는 그 리포트에 반영한 손익분기 요약, `checklist_done`/`checklist_total`은 체크리스트 진행이다(같은 지역·업종을 조건만 바꿔 여러 번 저장해도 카드끼리 구분).

브라우저 저장 키 없이 저장하면:
{{err_device}}
