"""에러 응답 형식 통일: {"error": {"code", "message", "fields"?}}  (화면에 message를 그대로 띄울 수 있게 한국어)."""
from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from .services.narrative import josa

FIELD_LABELS = {
    "area_code": "상권", "budget": "총 창업 예산", "monthly_rent_limit": "월 임대료",
    "labor_cost": "예상 인건비", "initial_investment": "초기 투자비", "business_goal": "창업 목표",
    "other_fixed": "기타 고정비", "loan_amount": "대출금", "loan_rate_annual": "대출 금리",
    "owner_salary": "목표 월수입(대표자)", "industry_code": "업종", "avg_ticket": "객단가",
    "cogs_rate": "원가율", "radius_m": "분석 반경", "lat": "위도", "lng": "경도", "q": "검색어",
    "area_codes": "비교 상권", "break_even_id": "손익분기 결과", "saved_report_id": "저장 리포트", "report_id": "리포트",
    "memo": "메모", "place_name": "장소 이름", "candidate_area_codes": "후보 상권",
    "interests": "관심 업종", "excluded_industries": "제외 업종", "licenses": "보유 자격", "categories": "업종 대분류",
    "user_type": "사용자 유형", "monthly_rent": "월 임대료", "other_variable_rate": "배달·기타 수수료", "limit": "개수",
    "analysis_id": "분석", "industry_codes": "업종", "cogs_rates": "분야별 원가율",
}


# 프레임워크 기본 오류 문구(영어)를 화면에 그대로 띄울 수 있게 한국어로
STD_DETAIL = {"Not Found": "요청한 주소를 찾을 수 없어요", "Method Not Allowed": "이 주소는 이 방식으로 요청할 수 없어요"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: list[dict] | None = None):
        self.status, self.code, self.message, self.fields = status, code, message, fields


def _field_msg(err: dict) -> dict:
    loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query", "path")]
    # 목록 번호·딕셔너리 키(licenses.0, cogs_rates.기타.[key])가 아니라 사람이 아는 항목 이름으로 말한다
    named = [x for x in loc if x in FIELD_LABELS]
    field = named[-1] if named else (loc[-1] if loc else "")
    # 본문 전체가 빠졌거나 모양이 틀리면(loc가 body뿐·목록 번호) 항목 이름 대신 '요청 내용'
    label = FIELD_LABELS.get(field, field) if field and not field.isdigit() else "요청 내용"
    t = err.get("type", "")
    if t == "json_invalid":
        return {"field": ".".join(loc), "message": "요청 내용(JSON) 형식을 확인해 주세요"}
    if t == "missing":
        msg = f"{josa(label, '을/를')} 입력해 주세요"
    elif t in ("greater_than_equal", "greater_than"):
        msg = f"{josa(label, '은/는')} {err.get('ctx', {}).get('ge', err.get('ctx', {}).get('gt', 0))} 이상이어야 해요"
    elif t in ("less_than_equal", "less_than"):
        msg = f"{label} 값이 너무 커요"
    elif t.startswith("string_too_short"):
        msg = f"{josa(label, '이/가')} 너무 짧아요"
    elif t == "string_too_long":
        msg = f"{josa(label, '이/가')} 너무 길어요"
    elif t == "too_long":                                   # 목록 개수 초과(관심 업종 20개 등)
        msg = f"{josa(label, '은/는')} {err.get('ctx', {}).get('max_length', '')}개까지 고를 수 있어요"
    elif t in ("int_parsing", "float_parsing", "int_type", "float_type"):
        msg = f"{josa(label, '은/는')} 숫자로 입력해 주세요"
    elif t == "value_error":
        msg = str(err.get("ctx", {}).get("error", err.get("msg", "")))
    elif label == "요청 내용":                               # 본문이 객체(JSON)가 아닌 경우(배열·문자열·폼 전송)
        msg = "요청 내용(JSON 객체)을 확인해 주세요"
    else:
        msg = f"{label} 값을 확인해 주세요"
    return {"field": ".".join(loc), "message": msg}


def install(app: FastAPI):
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        body = {"error": {"code": e.code, "message": e.message}}
        if e.fields:
            body["error"]["fields"] = e.fields
        return JSONResponse(status_code=e.status, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        fields = [_field_msg(err) for err in e.errors()]
        return JSONResponse(status_code=422, content={"error": {
            "code": "VALIDATION_ERROR", "message": fields[0]["message"] if fields else "입력값을 확인해 주세요",
            "fields": fields}})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, e: StarletteHTTPException):
        path = request.url.path
        if (e.status_code == 404 and getattr(request.app.state, "spa", False) and request.method in ("GET", "HEAD")
                and path != "/api" and not path.startswith(("/api/", "/assets/"))):
            # 화면 주소를 '#/' 없이 연 경우(/reports, /area?x=… 등) — JSON 404 대신 같은 화면으로(검색어 유지)
            rest = path.lstrip("/")
            if rest in ("", "index.html"):
                return RedirectResponse("/" + (f"?{request.url.query}" if request.url.query else ""))
            return RedirectResponse(f"/#/{rest}" + (f"?{request.url.query}" if request.url.query else ""))
        msg = STD_DETAIL.get(e.detail, e.detail) if isinstance(e.detail, str) else "요청을 처리할 수 없어요"
        return JSONResponse(status_code=e.status_code, content={"error": {"code": f"HTTP_{e.status_code}", "message": msg}},
                            headers=getattr(e, "headers", None))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception):
        # 예상 못 한 오류도 화면이 읽을 수 있는 같은 형식(JSON)으로. 자세한 내용은 서버 로그에만 남는다.
        return JSONResponse(status_code=500, content={"error": {
            "code": "INTERNAL_ERROR", "message": "일시적인 오류가 생겼어요. 잠시 후 다시 시도해 주세요"}})
