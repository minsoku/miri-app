"""코드성 기준 데이터: 관심 업종 칩(SB-04), 데이터 출처, 분기 표기."""
from __future__ import annotations
from datetime import date

# SB-04 관심 업종 칩 → 서울시 상권분석서비스 업종 코드 (칩 하나가 여러 업종일 수 있음)
DISPLAY_GROUPS = [
    {"group": "카페·디저트", "color": "#F49E0B", "codes": ["CS100010"]},
    {"group": "분식·간이음식", "color": "#2F6BFF", "codes": ["CS100008"]},
    {"group": "한식·백반", "color": "#16A34A", "codes": ["CS100001"]},
    {"group": "치킨·호프", "color": "#F04444", "codes": ["CS100007", "CS100009"]},
    {"group": "편의점", "color": "#0EA5E9", "codes": ["CS300002"]},
    {"group": "베이커리", "color": "#A855F7", "codes": ["CS100005"]},
]
CODE_TO_GROUP = {c: g["group"] for g in DISPLAY_GROUPS for c in g["codes"]}

# POLICY: '비슷한 업종' 대안(한줄 결론·체크리스트의 업종 변경 제안)은 같은 계열 안에서만 찾는다.
#   대분류(외식·서비스·소매)만 같으면 PC방 → 자동차수리처럼 경험·설비가 전혀 다른 업종이 제안되기 때문.
_FAMILIES = {
    "일반 음식점": ["CS100001", "CS100002", "CS100003", "CS100004"],
    "간편식": ["CS100006", "CS100008"],
    "주점·치킨": ["CS100007", "CS100009"],
    "카페·베이커리": ["CS100005", "CS100010"],
    "학원": ["CS200001", "CS200002", "CS200003", "CS200004"],
    "체육 시설·강습": ["CS200005", "CS200017", "CS200024"],
    "의료": ["CS200006", "CS200007", "CS200008", "CS200009"],
    "전문 서비스": ["CS200010", "CS200011", "CS200012", "CS200013", "CS200014", "CS200015"],
    "구기 오락": ["CS200016", "CS200018"],
    "PC·게임": ["CS200019", "CS200020", "CS200021"],
    "노래·영상": ["CS200037", "CS200039"],
    "차량 정비": ["CS200025", "CS200026", "CS200027"],
    "가전·통신 수리": ["CS200023", "CS200032"],
    "미용": ["CS200028", "CS200029", "CS200030"],
    "사진·녹음": ["CS200040", "CS200041"],
    "사무 대행": ["CS200042", "CS200044"],
    "숙박": ["CS200034", "CS200035"],
    "학습·주거 공간": ["CS200036", "CS200038"],
    "대여": ["CS200045", "CS200046", "CS200047"],
    "편의점·슈퍼": ["CS300001", "CS300002"],
    "식품 전문점": ["CS300006", "CS300007", "CS300008", "CS300009", "CS300010"],
    "의류": ["CS300011", "CS300012", "CS300013"],
    "신발·가방": ["CS300014", "CS300015"],
    "화장품·미용재료": ["CS300022", "CS300023"],
    "전자·통신 판매": ["CS300003", "CS300004", "CS300032"],
    "건강·의료용품": ["CS300016", "CS300018", "CS300019"],
    "서적·문구": ["CS300020", "CS300021"],
    "스포츠용품": ["CS300024", "CS300025"],
    "악기·예술품": ["CS300034", "CS300041"],
    "가구·인테리어": ["CS300030", "CS300031", "CS300035", "CS300036"],
    "철물·재생": ["CS300033", "CS300040"],
    "자동차 판매": ["CS300037", "CS300038", "CS300039"],
    # 비슷한 업종이 없는 단독 업종(대안 업종 제안 안 함)
    "기타": ["CS200022", "CS200031", "CS200033", "CS200043", "CS300005", "CS300017", "CS300026", "CS300027",
           "CS300028", "CS300029", "CS300042", "CS300043"],
}
INDUSTRY_FAMILY = {c: f for f, codes in _FAMILIES.items() for c in codes if f != "기타"}

# 면허는 아니지만 개업 전 등록·신고와 시설·인력 기준이 까다로운 업종(체크리스트 '인허가' 항목)
REGISTRATION_NOTES = {
    "CS200025": "자동차관리사업(정비업) 등록 — 시설·정비 기술인력 기준 충족 필요",
    "CS200027": "이륜자동차 정비업 신고 요건 확인",
    "CS200001": "학원 설립·운영 등록(교육청) — 강의실 면적·시설 기준 확인",
    "CS200002": "학원 설립·운영 등록(교육청) — 강의실 면적·시설 기준 확인",
    "CS200003": "학원 설립·운영 등록(교육청) — 강의실 면적·시설 기준 확인",
    "CS200004": "학원 설립·운영 등록(교육청) — 강의실 면적·시설 기준 확인",
    "CS200019": "인터넷컴퓨터게임시설제공업 등록 — 청소년 출입·시설 기준 확인",
    "CS200037": "노래연습장업 등록 — 방음·소방 시설 기준 확인",
    "CS200034": "숙박업 신고 — 공중위생·소방 시설 기준 확인",
    "CS200036": "다중이용업(고시원) 안전시설 완비 증명 — 소방 시설 기준 확인",
}

# 원천 데이터(서울 열린데이터광장 · 서울시 상권분석서비스, 자치구 단위). file = data_raw 파일명
DATA_SOURCES = [
    {"key": "stores", "source_name": "서울시 상권분석서비스(점포-자치구)", "dataset_code": "OA-22173", "file_name": "점포_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr/dataList/OA-22173/S/1/datasetView.do",
     "description": "업종별 점포 수·개업/폐업 점포 수·프랜차이즈 점포 수"},
    {"key": "sales", "source_name": "서울시 상권분석서비스(추정매출-자치구)", "dataset_code": "OA-22176", "file_name": "매출_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr/dataList/OA-22176/S/1/datasetView.do",
     "description": "업종별 분기 추정 매출·결제 건수(요일·시간대·성별·연령)"},
    {"key": "floating", "source_name": "서울시 상권분석서비스(길단위인구-자치구)", "dataset_code": "OA-22179", "file_name": "유동인구_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr/dataList/OA-22179/S/1/datasetView.do",
     "description": "분기 유동인구(성별·연령·시간대·요일)"},
    {"key": "resident", "source_name": "서울시 상권분석서비스(상주인구-자치구)", "dataset_code": None, "file_name": "상주인구_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr",
     "description": "상주인구·가구 수"},
    {"key": "working", "source_name": "서울시 상권분석서비스(직장인구-자치구)", "dataset_code": None, "file_name": "직장인구_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr",
     "description": "직장인구"},
    {"key": "income", "source_name": "서울시 상권분석서비스(소득소비-자치구)", "dataset_code": None, "file_name": "소득소비_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr",
     "description": "월 평균 소득·지출"},
    {"key": "change", "source_name": "서울시 상권분석서비스(상권변화지표-자치구)", "dataset_code": "OA-15567", "file_name": "상권변화_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://data.seoul.go.kr/dataList/OA-15567/S/1/datasetView.do",
     "description": "상권변화지표·운영/폐업 영업개월 평균"},
    {"key": "rent", "source_name": "서울시 우리마을가게 상권분석 임대시세(자치구)", "dataset_code": None, "file_name": "임대료_자치구.csv",
     "source_type": "CSV", "update_cycle": "분기", "url": "https://golmok.seoul.go.kr/",
     "description": "3.3㎡당 월 환산임대료(원)"},
    {"key": "boundary", "source_name": "서울시 행정구역 시군구 경계", "dataset_code": "OA-11677", "file_name": "seoul_districts.geojson",
     "source_type": "MANUAL", "update_cycle": "비정기", "url": "https://github.com/southkorea/seoul-maps",
     "description": "자치구 경계 폴리곤(도로명주소 2015, southkorea/seoul-maps 가공본)"},
]
# 공개되어 있지만 아직 적재하지 않은 소스(참고 레퍼런스 2장) — data_sources에 등록만
PLANNED_SOURCES = [
    {"source_name": "소상공인시장진흥공단 상가(상권)정보 API", "source_type": "API", "update_cycle": "분기",
     "dataset_code": "15012005", "url": "https://www.data.go.kr/data/15012005/openapi.do",
     "description": "점포 좌표·업종 (상권 단위 확장 시 사용 예정)"},
    {"source_name": "서울시 상권분석서비스(점포·추정매출·영역-상권)", "source_type": "CSV", "update_cycle": "분기",
     "dataset_code": "OA-15577", "url": "https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do",
     "description": "상권 단위 데이터 (다운로드 후 적재하면 상권 단위 분석으로 전환)"},
    {"source_name": "기업마당 지원사업 정보", "source_type": "API", "update_cycle": "일",
     "dataset_code": None, "url": "https://www.bizinfo.go.kr",
     "description": "정책 지원사업 공고 (policy_supports 갱신)"},
]


def quarter_label(q: int) -> str:
    return f"{q // 10}년 {q % 10}분기"


def quarter_start(q: int) -> date:
    return date(q // 10, (q % 10 - 1) * 3 + 1, 1)


def days_in_quarter(q: int) -> int:
    y, k = q // 10, q % 10
    start = quarter_start(q)
    end = date(y + 1, 1, 1) if k == 4 else date(y, k * 3 + 1, 1)
    return (end - start).days
