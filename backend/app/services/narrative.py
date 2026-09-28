"""M-06 화면 문장 템플릿 (규칙 기반).  엔진 explain.py(저장용 긴 근거)와 별도로, 모바일 카드용 짧은 문장·칩을 만든다.
모든 문장은 계산 결과 숫자에서만 만들어지고, 숫자가 없으면 해당 문장을 생략한다(추측 문장 없음).
등급 표현은 화면 배지와 같은 컷(40/70/90, miri_engine.config)을 쓴다 — 문장과 배지가 서로 다른 말을 하지 않게."""
from __future__ import annotations
import math
import numbers
from miri_engine.config import risk_grade, SuitabilityParams

GRADE_ORDER = {"낮음": 0, "보통": 1, "높음": 2, "고위험": 3}
SLOT_LABEL = {"t00": "00~06시", "t06": "06~11시", "t11": "11~14시", "t14": "14~17시", "t17": "17~21시", "t21": "21~24시"}
AGE_LABEL = {"a10": "10대", "a20": "20대", "a30": "30대", "a40": "40대", "a50": "50대", "a60": "60대 이상"}
LOC_WORD = {"낮음": "낮은 편", "보통": "중간", "높음": "높은 편", "고위험": "매우 높은 편"}
# 업종 대분류별 표현 — 외식업 문구(메뉴·회전율)가 세탁소·학원 체크리스트에 나오지 않게
OFFER = {"외식업": "메뉴", "서비스업": "서비스", "소매업": "상품"}
TARGETS = {"외식업": "객단가·회전율", "서비스업": "객단가·재방문율", "소매업": "객단가·구매 전환율"}


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사: josa('커피-음료','은/는') → '커피-음료는', josa('분식전문점','으로/로') → '분식전문점으로'."""
    a, b = pair.split("/")
    ch = word[-1] if word else ""
    if not ("가" <= ch <= "힣"):
        return f"{word}{a}({b})" if pair != "으로/로" else f"{word}(으)로"
    jong = (ord(ch) - 0xAC00) % 28
    if pair == "으로/로":
        return word + ("로" if jong in (0, 8) else "으로")      # 받침 없음 또는 ㄹ받침 → '로'
    return word + (a if jong else b)


def ok(x) -> bool:
    """유한한 숫자인지(numpy 숫자 포함, bool·문자열·None·NaN 제외)."""
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)


def won(x: float | None, unit: str = "원") -> str:
    """12,345,678 → '1,235만원', 123,456,789 → '1.23억원', 520,000,000 → '5.2억원', 9,000 → '9,000원'."""
    if not ok(x):
        return "-"
    x = float(x)
    if abs(x) >= 99_995_000:                     # 만원 단위로 반올림하면 10,000만원이 되는 값부터 억 단위
        return f"{x / 1e8:,.2f}".rstrip("0").rstrip(".") + f"억{unit}"      # 5.20억 → 5.2억, 3.00억 → 3억
    if abs(x) >= 1e5:
        return f"{x / 1e4:,.0f}만{unit}"
    if abs(x) >= 1e4:                            # 1만~10만: 15,000 → '1.5만원'(반올림으로 '2만원'이 되지 않게)
        return f"{x / 1e4:.1f}".rstrip("0").rstrip(".") + f"만{unit}"
    return f"{x:,.0f}{unit}"


def won_value(x: float) -> float:
    """won()이 화면에 보여 주는 값(원). 두 금액의 차이를 말할 때 '492만원 − 315만원 = 178만원'처럼 어긋나지 않게
    표시값끼리 뺀다."""
    x = float(x)
    # 정수(원)로 돌려준다: float("1.10") * 1e8 = 110000000.00000001처럼 곱셈 오차가 비교를 틀리게 하지 않게
    if abs(x) >= 99_995_000:
        return round(float(f"{x / 1e8:.2f}") * 1e8)
    if abs(x) >= 1e5:
        return round(float(f"{x / 1e4:.0f}") * 1e4)
    if abs(x) >= 1e4:
        return round(float(f"{x / 1e4:.1f}") * 1e4)
    return round(float(f"{x:.0f}"))


def _won_step(x: float) -> float:
    """won() 표시 단위(원): 억 단위 소수 둘째 자리=100만원, 만원, 1만~10만은 천원, 그 아래는 1원."""
    a = abs(x)
    return 1e6 if a >= 99_995_000 else 1e4 if a >= 1e5 else 1e3 if a >= 1e4 else 1.0


def won_floor_below(limit: float, now: float) -> float:
    """'X 이하로 낮추기'의 X: 한도를 표시 단위에서 내림하고, 지금 금액(표시값)과 같아 보이면 한 단위 더 내린다
    ('2,043만원 이하로 낮추기(지금 2,043만원, 월 0원)' 같은 문장 방지)."""
    step = _won_step(limit)
    t = round(math.floor(float(limit) / step) * step)
    shown_now = won_value(now)
    while t >= shown_now and t > 0:
        t -= round(step)
    return float(max(t, 0))


def won1(x: float | None) -> str:
    """작은 금액(3.3㎡당 임대료 등): 1만~100만원은 소수 첫째 자리까지. 105,600 → '10.6만원'."""
    if ok(x) and 1e4 <= abs(float(x)) < 1e6:
        return f"{float(x) / 1e4:,.1f}만원"
    return won(x)


def pct(x: float | None, digits: int = 1) -> str:
    return "-" if not ok(x) else f"{x * 100:.{digits}f}%"


def signed_pct(x: float, digits: int = 1) -> str:
    """증감률: +3.2% / −0.9%. 반올림하면 0이 되는 값은 부호 없이 '0.0%'('−0.0%' 방지)."""
    if abs(x) * 10 ** (digits + 2) < 0.5:
        return f"{0:.{digits}f}%"
    return f"{x:+.{digits}%}".replace("-", "−")       # 화면의 요인 효과(−2%)와 같은 빼기 기호


def times(r: float) -> str:
    """달성배율 표기: 1.24배. 너무 작으면 '0.00배' 대신 '0.01배 미만'."""
    return f"{r:.2f}배" if r >= 0.005 else "0.01배 미만"


def _ra(t: str) -> str:          # '1.24배라' / '0.01배 미만이라'
    return t + ("이라" if t.endswith("미만") else "라")


def _yeyo(t: str) -> str:        # '1.24배예요' / '0.01배 미만이에요'
    return t + ("이에요" if t.endswith("미만") else "예요")


def shown_effect(f: dict) -> int:
    """화면에 보이는 요인 효과 크기(정수 %, 사사오입) — 라벨('약간')·체크리스트·알약 기준을 화면 숫자와 맞춘다."""
    d = f.get("effect_display")
    return abs(int(d)) if ok(d) else int(math.floor(abs(float(f["effect_pct"])) + 0.5))


SMALL_LABELS = {"short_life": ("지역 전체 폐업 점포 수명 약간 짧은 편", "지역 전체 폐업 점포 수명 약간 긴 편"),
                "low_sales": ("점포당 매출 약간 낮은 편", "점포당 매출 약간 높은 편"),
                "ind_base": ("업종 자체 폐업률 약간 높은 편", "업종 자체 폐업률 약간 낮은 편"),
                "area_hist": ("이 지역 폐업 이력 약간 많은 편", "이 지역 폐업 이력 약간 적은 편"),
                "entry_heat": ("신규 개업 약간 많은 편", "신규 개업 약간 적은 편")}


def factor_label(f: dict, ctx: dict | None = None) -> str:
    """상대 요인 라벨을 실제 증감과 맞춘다. 모델은 '같은 업종 다른 지역보다 점포 증가율이 높은지'를 보므로
    이 지역 점포가 줄었어도(−1%) 위험(+)일 수 있다 → '점포 증가율 높음' 대신 '점포 감소 폭이 작음'."""
    c, x, up = f["factor_code"], ctx or {}, f["effect_pct"] > 0
    if c == "store_surge" and ok(x.get("store_growth")):
        g = x["store_growth"]
        s = 0 if abs(g) < 0.0005 else (1 if g > 0 else -1)
        if s == 0:
            return "점포 수 거의 그대로"
        if up:
            return "점포 늘어나는 중" if s > 0 else "점포 감소 폭이 작음"
        return "점포 줄어드는 중" if s < 0 else "점포 증가 폭이 작음"
    if c == "sales_decline" and ok(x.get("sales_growth")):
        g = x["sales_growth"]
        s = 0 if abs(g) < 0.0005 else (1 if g > 0 else -1)
        if s == 0:
            return "매출 거의 그대로"
        if up:
            return "매출 줄어드는 중" if s < 0 else "매출 증가 폭이 작음"
        return "매출 늘어나는 중" if s > 0 else "매출 감소 폭이 작음"
    if c == "entry_heat" and entry_smoothed(f, x):
        return "개업 비율(보정값) 높은 편" if up else "개업 비율(보정값) 낮은 편"
    if c == "area_hist" and ok(x.get("rate_eb")) and ok(x.get("ind_avg")) and pct(annual(x["rate_eb"])) == pct(x["ind_avg"]):
        return "이 지역 폐업 이력 업종 평균 수준"      # 설명 줄의 두 폐업률이 같아 보이면 '많음/적음'이라 하지 않는다
    if c == "low_sales" and not up and ok(x.get("sales_outlier")):
        # 대형 점포가 섞인 듯한 평균(서울 중간값의 3배 이상)이면 '약간 높은 편'이 아니라 참고용이라고(SB-05 알약과 같은 뜻)
        return "점포당 매출 높음(대형 점포 가능·참고용)"
    if c in SMALL_LABELS and shown_effect(f) < 3:
        # 효과가 작으면(3% 미만) '짧은 편/낮음' 대신 '약간' — 체크리스트·운영자금 기준(3% 이상만 반영)과 어긋나 보이지 않게
        return SMALL_LABELS[c][0 if up else 1]
    return f["label"]


def annual(q: float) -> float:
    """분기 폐업률 → 연 폐업률(4분기 복리). 곱셈으로 적어 데모(TypeScript)와 같은 값이 나오게."""
    a = 1.0 - min(max(float(q), 0.0), 1.0)
    return 1.0 - (a * a) * (a * a)


def entry_smoothed(f: dict, x: dict) -> bool:
    """신규 개업 요인이 '보정 때문에' 실제 개업 비율과 반대 방향인지. 점포가 적은 지역은 개업 비율을 업종 평균 쪽으로
    당겨(EB) 비교하므로, 실제 개업이 0곳이어도 '높은 편'이 될 수 있다 → 라벨·설명을 보정값이라고 밝힌다."""
    ope, exp4, mu = x.get("ope4"), x.get("exp4"), x.get("mu_ind_entry")
    if not (ok(ope) and ok(exp4) and exp4 > 0 and ok(mu)):
        return False
    raw = ope / exp4
    return (f["effect_pct"] > 0 and raw < mu) or (f["effect_pct"] < 0 and raw > mu)


def relabel(factors: list[dict], ctx: dict | None) -> list[dict]:
    """요인 목록의 라벨·설명 문장을 factor_label로 바꾼 사본."""
    out = []
    for f in factors:
        lab = factor_label(f, ctx)
        g = dict(f, label=lab)
        if "explanation" in f and "effect_display" in f:
            d = f["effect_display"]
            g["explanation"] = f"{lab}: 예상 폐업률 {'+' if f['effect_pct'] > 0 else '−'}{abs(d)}%"
        out.append(g)
    return out


# ── SB-05 추천 카드 ─────────────────────────────────────────────────────
ACADEMY_CODES = ("CS200001", "CS200002", "CS200003", "CS200005")      # 학원 계열(손님이 학생 — '직장인 대상' 문구 제외)
LUNCH_BY_CODE = {"CS200031": "맡기고 찾는 손님이 몰리는 시간대에 인력 배치"}      # 세탁소: 예약·대기 문구가 맞지 않음


def peak_flags(profile: dict | None, category: str | None = None, industry_code: str | None = None) -> list[dict]:
    """매출 구성에서 운영상 의미 있는 쏠림. 임계값은 설명용 휴리스틱(모델 점수에는 쓰지 않음)."""
    if not profile:
        return []
    ts, out = profile.get("time_share") or {}, []
    lunch = LUNCH_BY_CODE.get(industry_code or "") or ("점심 시간대 수업·상담 인력 배치" if industry_code in ACADEMY_CODES else {
        "외식업": "회전율 높이는 메뉴·동선 설계", "소매업": "시간대 진열·계산대 인력 집중",
        "서비스업": "예약 시간 조정·인력 배치로 대기 줄이기"}.get(category or "", "시간대에 맞춘 인력 배치"))
    weekend = {"외식업": "주말 인력·재고 먼저 확보", "소매업": "주말 인력·재고 먼저 확보",
               "서비스업": "주말 인력·예약 먼저 확보"}.get(category or "", "주말 인력 먼저 확보")
    weekday = "평일 수업 시간 중심으로 운영 계획" if industry_code in ACADEMY_CODES else {
        "외식업": "직장인 대상 평일 메뉴·영업시간 구성", "소매업": "직장인 대상 평일 상품·영업시간 구성",
               "서비스업": "직장인 대상 평일 영업시간·예약 구성"}.get(category or "", "직장인 대상 평일 영업시간 구성")
    if ts.get("t11", 0) >= 0.30:
        out.append({"code": "lunch", "pill": "점심 피크 집중", "share": ts["t11"],
                    "action": f"점심 피크(11~14시, 매출 {ts['t11']:.0%}) {lunch}"})
    if ts.get("t17", 0) >= 0.40:
        out.append({"code": "dinner", "pill": "저녁 피크 집중", "share": ts["t17"],
                    "action": f"저녁 피크(17~21시, 매출 {ts['t17']:.0%})에 인력 집중 배치"})
    night = ts.get("t21", 0) + ts.get("t00", 0)
    if night >= 0.40:
        out.append({"code": "night", "pill": "야간 매출 의존", "share": night,
                    "action": f"야간(21~06시) 매출 {night:.0%} — 심야 인건비·안전 운영 계획"})
    we = profile.get("weekend_share")
    if ok(we) and we >= 0.40:
        out.append({"code": "weekend", "pill": "주말 매출 의존", "share": we,
                    "action": f"주말 매출 {we:.0%} — {weekend}"})
    elif ok(we) and we <= 0.15:
        out.append({"code": "weekday", "pill": "평일 위주 상권", "share": 1 - we,
                    "action": f"평일 매출 {1 - we:.0%} — {weekday}"})
    return out


def reason_short(it: dict) -> str:
    """카드용 두 문장: 매출 순위 + 폐업 위험.  예) '점포당 매출이 서울 25개 구 중 3위로 높은 편이에요. 폐업 위험은 보통이에요.'
    백분위('상위 12%')는 비교 대상이 25곳 남짓이라 과하게 정밀해 보여 순위로 보여준다. 배율 등 숫자는 reason_chips로."""
    parts = []
    rk, n, D = it.get("sales_rank"), it.get("sales_n"), it.get("D")
    if ok(rk) and ok(n) and ok(D):
        unit = it.get("unit") or "구"
        if n < 5:                                   # 비교 대상이 너무 적으면 '높은 편' 같은 평가를 하지 않는다
            parts.append(f"점포당 매출이 서울 {int(n)}개 {unit} 중 {int(rk)}위예요.")     # 참고용이라는 말은 score_note가 한다
        else:
            # 순위 ÷ 비교 대상 수로 표현(같은 8위가 25곳 중 '높은 편', 24곳 중 '중간'처럼 엇갈리지 않게)
            share = rk / n
            lvl = "높은 편" if share <= 0.3 else "낮은 편" if share > 0.7 else "중간"
            parts.append(f"점포당 매출이 서울 {int(n)}개 {unit} 중 {int(rk)}위로 {lvl}이에요.")
    g, loc = it.get("risk_grade"), it.get("risk_pct_in_ind")
    if g in ("높음", "고위험") and ok(loc) and risk_grade(loc) == "낮음":
        parts.append(f"종합 폐업 위험은 {'매우 ' if g == '고위험' else ''}높지만 같은 업종끼리 비교하면 "
                     f"이 지역은 입지 위험이 낮은 편이에요({int(loc)}).")
    else:
        parts.append({"낮음": "폐업 위험은 낮아요.", "보통": "폐업 위험은 보통이에요.", "높음": "폐업 위험이 높은 편이에요.",
                      "고위험": "폐업 위험이 매우 높아요."}.get(g, ""))
    return " ".join(x for x in parts if x)


def reason_chips(it: dict) -> list[str]:
    chips = []
    if ok(it.get("sales_ps_m")):
        chips.append(f"점포당 월매출 {won(it['sales_ps_m'])}")
    if ok(it.get("pred_annual_rate")):
        chips.append(f"예상 연 폐업률 {pct(it['pred_annual_rate'])}")
    if ok(it.get("achievability_ratio")):
        base = "필요 매출(목표 월수입 포함)" if it.get("owner_included") else "손익분기"
        # 대형 점포가 섞인 듯한 평균이면 배율도 참고용(SB-07·08·09와 같은 말)
        chips.append(f"평균 매출이 {base}의 {times(it['achievability_ratio'])}" + ("(참고용)" if ok(it.get("sales_outlier")) else ""))
    elif it.get("cogs_missing"):
        # 원가율을 모르는 분야(소매·서비스업을 조건에서 안 넣음)는 '매출 ≥ 월 고정비'만 봤다 — 순위만 보고 흑자로 읽지 않게
        chips.append("손익분기 미확인(원가율 미입력)")
    if ok(it.get("stores_avg4")):
        chips.append(f"점포 {it['stores_avg4']:,.0f}개")
    return chips


OUTLIER_PILL = "매출이 유난히 높음(대형 점포 가능)"


def caution_pills(it: dict, profile: dict | None) -> list[str]:
    """카드 주의 알약(최대 3개, 위험 신호만 — 시간대 쏠림 같은 운영 특성은 peak로 따로). 손익분기 미달을 맨 앞에."""
    pills = []
    if ok(it.get("achievability_ratio")) and it["achievability_ratio"] < 1:
        pills.append("평균 매출로 필요 매출(목표 월수입 포함) 미달" if it.get("owner_included") else "평균 매출로 손익분기 미달")
    if ok(it.get("sales_outlier")):
        pills.append(OUTLIER_PILL)
    if it.get("risk_grade") == "고위험":
        pills.append("폐업 위험 매우 높음")
    elif it.get("risk_grade") == "높음":
        pills.append("폐업 위험 높음")
    ups = [f for f in it.get("risk_factors") or [] if f["effect_pct"] > 0 and shown_effect(f) >= 5
           and f["factor_code"] != "ind_base"]
    if ups:
        pills.append(ups[0]["label"])
    if it.get("confidence") == "낮음":
        pills.append("데이터 적음")
    return pills[:3]


# ── SB-06 위험도 ─────────────────────────────────────────────────────────
def risk_summary(area_name: str, r: dict, fallback: bool = False) -> str:
    """종합 위험·입지 위험 문장. 표현은 배지 등급(40/70/90)과 같은 구간을 쓴다."""
    score, g = int(r["risk_score"]), r["risk_grade"]
    top = max(1, 100 - score)
    pos = {"낮음": "위험이 낮은 편이에요.", "보통": "중간 수준이에요.", "높음": f"위험이 높은 편이에요(상위 {top}%).",
           "고위험": f"위험이 매우 높아요(상위 {top}%)."}.get(g, "")
    s = (f"{area_name} {r['industry_name']}의 향후 1년 예상 폐업률은 {pct(r['pred_annual_rate'])}로, "
         f"서울 전체 지역·업종 조합 중 {pos}")
    if fallback:
        return s + " 이 지역에는 같은 업종 점포가 없어 입지 비교는 하지 않았어요."
    loc = int(r["risk_pct_in_ind"])
    return s + f" 같은 업종끼리 비교하면 이 지역 입지 위험은 {LOC_WORD[risk_grade(loc)]}이에요({loc})."


def factor_detail(f: dict, ctx: dict | None = None) -> str:
    """요인 카드 아래 한 줄: 무엇을 무엇과 비교했는지 + 이 지역 실제 값(있으면).
    상대 요인은 '같은 업종 다른 지역과 비교한 순위'라서, 실제 값이 −5%여도 업종 전체가 더 줄었으면 위험(+)이 될 수 있다."""
    c, x = f["factor_code"], ctx or {}
    same = "같은 업종 다른 지역과 비교"
    if c == "ind_base":
        if ok(x.get("ind_avg")) and ok(x.get("seoul_avg")):
            return f"업종 전체(서울) 연 폐업률 {pct(x['ind_avg'])} · 서울 전 업종 {pct(x['seoul_avg'])}"
        return "업종 전체(서울) 폐업률을 전 업종 평균과 비교"
    if c == "area_hist":
        if ok(x.get("rate_eb")) and ok(x.get("ind_avg")):
            # 모델이 비교하는 두 값(보정한 이 지역 폐업률 vs 업종 평균)을 그대로 보여 준다 — '폐업 434곳 ÷ 점포 2,597곳'을
            # 직접 나눈 값은 분모(점포-분기)·보정이 달라 라벨(많음/적음)과 어긋나 보일 수 있다
            local, avg, lw = pct(annual(x["rate_eb"])), pct(x["ind_avg"]), x.get("local_weight")
            clo = f"{x['clo4']:,.0f}곳" if ok(x.get("clo4")) else None
            if ok(lw) and lw < 0.8:                 # 보정이 크면 순서를 바꿔 '폐업 0곳인데 폐업률 6.2%'처럼 읽히지 않게
                return (f"이 지역 최근 1년 폐업 {clo} — " if clo else "") + f"업종 평균({avg}) 쪽으로 보정한 폐업률 {local}로 비교"
            return f"이 지역 최근 1년 폐업률 {local}" + (f"(폐업 {clo})" if clo else "") + f" · 업종 평균 {avg}"
        if ok(x.get("clo4")) and ok(x.get("stores_avg4")) and x["stores_avg4"] > 0:
            return (f"이 지역 최근 1년 폐업 {x['clo4']:,.0f}곳(평균 점포 {x['stores_avg4']:,.0f}곳) — "
                    "점포가 적은 곳은 서울 평균 쪽으로 보정해 비교")
        return "이 지역·업종의 최근 1년 폐업 이력을 업종 평균과 비교"
    if c == "sales_decline":
        v = x.get("sales_growth")
        return f"이 지역 같은 업종 매출 전년 대비 {signed_pct(v)} — {same}" if ok(v) else f"이 지역 같은 업종 매출 추세를 {same}"
    if c == "store_surge":
        v = x.get("store_growth")
        return f"이 지역 같은 업종 점포 수 전년 대비 {signed_pct(v)} — {same}" if ok(v) else f"이 지역 같은 업종 점포 수 추세를 {same}"
    if c == "entry_heat":
        v = x.get("ope4")
        if ok(v) and entry_smoothed(f, x):
            return f"최근 1년 같은 업종 개업 {v:,.0f}곳 — 점포가 적어 서울 같은 업종 평균 쪽으로 보정한 개업 비율로 비교"
        return f"최근 1년 같은 업종 개업 {v:,.0f}곳 — 점포 대비 개업 비율을 {same}" if ok(v) else f"점포 대비 개업 비율을 {same}"
    if c == "rent_burden":
        return f"임대료 ÷ 점포당 매출을 {same}"
    if c == "density":
        return f"유동인구 대비 점포 수를 {same}"
    if c == "low_sales":
        v = x.get("sales_ps_m")
        return f"점포당 월매출 {won(v)} — {same}" if ok(v) else f"점포당 월매출을 {same}"
    if c == "short_life":
        v = x.get("closed_months4")
        return (f"이 지역 전 업종 폐업 점포 평균 영업 {v:.0f}개월 — 다른 지역과 비교(업종별 값 아님)" if ok(v)
                else "이 지역 전 업종 폐업 점포의 평균 영업 기간을 다른 지역과 비교")
    if c == "ind_trend":
        v = x.get("ind_sales_growth")
        return f"업종 전체(서울) 매출 전년 대비 {signed_pct(v)}" if ok(v) else "업종 전체(서울) 매출 추세"
    return ""


# ── SB-08 액션 리포트 ─────────────────────────────────────────────────────
def months_floor(m: float) -> str:
    """운영비 개월 수 표시: 소수 첫째 자리 내림(권장 개월 수에 못 미치는 값이 반올림으로 같아 보이지 않게)."""
    s = f"{math.floor(m * 10 + 1e-9) / 10:.1f}"
    return s[:-2] if s.endswith(".0") else s          # 6.0 → '6'(6개월분), 5.95 → '5.9'


SALES_OUTLIER_X = SuitabilityParams().outlier_sales_x   # 점포당 매출이 서울 같은 업종 중간값의 3배 이상 → 대형 점포 가능성(추천 제외)


def sales_outlier(row) -> float | None:
    """점포당 매출 ÷ 서울 같은 업종 중간값(3배 이상일 때만, 아니면 None)."""
    if row is None:
        return None
    v, med = row.get("sales_ps_m"), row.get("sales_med")
    if not (ok(v) and ok(med)) or med <= 0 or v / med < SALES_OUTLIER_X:
        return None
    return float(v / med)


BIG_STORE = {"소매업": "도매 상가·대형 점포", "외식업": "대형 매장", "서비스업": "대형·기업형 점포"}


def data_caveat(focus: dict) -> str | None:
    """매출 추정 자체가 흔들리는 경우: 비교할 구가 적거나(5곳 미만) 대형 점포가 섞인 듯한 경우."""
    n, x = focus.get("few_sales_areas"), focus.get("sales_outlier")
    if ok(n):
        return f"매출을 비교할 구가 {int(n)}곳뿐이라 매출 추정은 참고용이에요."
    if ok(x):
        kind = BIG_STORE.get(focus.get("category") or "", "대형 점포")
        return (f"이 지역 점포당 매출이 서울 같은 업종 중간값의 {x:.1f}배로 높아 {josa(kind, '이/가')} 섞였을 수 있어요 — "
                "비슷한 규모 점포의 실제 매출을 확인하세요.")
    return None


def risk_is(g: str, rate: str, end: str) -> str:
    """낮음·보통 등급 문장 조각: end '고'(그리고) / '지만' / '요'(문장 끝)."""
    stem = {"낮음": ("낮고", "낮지만", "낮아요"), "보통": ("보통 수준이고", "보통 수준이지만", "보통 수준이에요")}.get(
        g, (f"{g}이고", f"{g}이지만", f"{g}이에요"))
    word = stem[{"고": 0, "지만": 1, "요": 2}[end]]
    return f"폐업 위험이 {word}(예상 연 폐업률 {rate})" + ("." if end == "요" else "")


def budget_caveat(focus: dict) -> str | None:
    """예산·운영자금 단서: 투자비 > 예산이면 부족액, 예산을 투자비로 다 쓰면 '운영자금이 없어요', 권장 개월 수
    (체크리스트와 같은 기준: 보통 6개월, 업종 폐업률이 높거나 폐업 점포 수명이 짧으면 12개월) 미만이면 개월 수."""
    over = focus.get("over_budget")
    if ok(over) and over > 0:
        return f"초기 투자비가 예산보다 {won(over)} 많아 운영자금이 남지 않아요. 자금 계획부터 다시 세우세요."
    rm, months = focus.get("reserve_months"), int(focus.get("runway_months") or 6)
    if ok(rm) and rm < months:
        inv = float(focus.get("investment") or 0)
        if rm <= 0 and inv > 0:
            return "예산을 초기 투자비로 모두 써서 운영자금이 없어요. 자금 계획부터 다시 세우세요."
        lead = "예산에서 투자비를 빼면" if inv > 0 else "예산으로는"
        # 소수 첫째 자리 내림: 11.96개월이 '12.0개월분뿐이라(권장 12개월분)'처럼 보이지 않게, 1개월 미만은 '0.0개월분' 대신
        have = "1개월분도 안 돼" if rm < 1 else f"{months_floor(rm)}개월분뿐이라"
        return f"{lead} 운영비가 {have} 운영자금({months}개월분)부터 마련하세요."
    return None


def one_liner(area_label: str, focus: dict, alt: dict | None, be: dict | None, area_alt: dict | None = None) -> str:
    """한줄 결론(규칙 기반, 핵심 한두 문장 + 꼭 필요한 단서). 우선순위(명세서 11절): 지역 데이터 없음 → 자격 필요
    → 폐업 위험 높음 → 손익분기 미달 → 개설 조건(수요 검증·평균 매출 < 고정비) → 입지 위험 매우 높음(주의 업종) → 진입 검토.
    focus: 업종 행 + location_risk_pct·fallback·confidence·block(개설 조건 문장)
    alt: 같은 분야에서 예상 폐업률이 확실히 낮은 업종 / be: 손익분기 결과 / area_alt: 같은 업종 입지 위험이 낮은 인근 지역."""
    name, g = focus["industry_name"], focus["risk_grade"]
    rate = pct(focus["pred_annual_rate"])
    subj = f"{area_label} {josa(name, '은/는')}"
    high = g in ("높음", "고위험")
    loc = focus.get("location_risk_pct")
    ratio = be.get("achievability_ratio") if be else None
    short = ok(ratio) and ratio < 1
    owner = float(((be or {}).get("composition") or {}).get("owner_salary") or 0)
    # 목표 월수입을 넣었으면 배율의 기준은 손익분기가 아니라 '필요 매출(목표 월수입 포함)' — SB-05 칩·SB-07·SB-08·체크리스트와 같은 말
    bep = "필요 매출(목표 월수입 포함)" if owner > 0 else "손익분기"
    alt_s = (f"비슷한 업종인 {josa(alt['industry_name'], '은/는')} 예상 연 폐업률이 {pct(alt['pred_annual_rate'])}"
             f"(위험 {alt['risk_grade']})예요 — 함께 비교해 보세요." if alt else None)
    # 인근 구는 평균 매출로 지금 비용을 감당할 수 있는 곳만 권한다(위험도 화면의 '입지 위험이 더 낮은 인근 지역'과 다를 수 있는 이유)
    # 원가율을 모르는 업종은 '평균 매출 ≥ 월 고정비'만 봤으니 '감당할 만한'이라고 하지 않는다
    afford = ("평균 매출로 지금 비용을 감당할 만한" if (area_alt or {}).get("cogs_known", True)
              else f"평균 매출이 지금 월 고정비{'(목표 월수입 포함)' if (area_alt or {}).get('owner_included') else ''}보다 큰")
    area_s = (f"이 업종을 하려면 입지 위험이 더 낮고 {afford} {area_alt['area_name']}"
              f"(입지 위험 {area_alt['location_risk_pct']}, 예상 연 폐업률 {pct(area_alt['pred_annual_rate'])})도 비교해 보세요."
              if area_alt else None)

    if focus.get("fallback"):
        return (f"{area_label}에는 최근 1년 {name} 점포가 없어 서울 같은 업종 평균으로만 추정했어요(예상 연 폐업률 {rate}). "
                "이 지역 수요는 검증되지 않았으니 주변 상권을 현장에서 먼저 확인하세요.")
    if focus.get("license"):
        # 자격이 없으면 위험·매출보다 먼저: 열 수 없는 업종을 '검토해 볼 만해요'·'다른 구와 비교'로 안내하지 않는다
        if short:                                  # 자격이 있어도 적자인 구조면 그것도 함께(카드의 '위험 0.29배'와 어긋나지 않게)
            return (f"{subj} {focus['license']} 자격이 있어야 열 수 있어요. 자격이 있어도 평균 매출이 {bep}의 "
                    f"{_ra(times(ratio))} 지금 비용 구조로는 모자라요(폐업 위험 {g}, 예상 연 폐업률 {rate}).")
        return (f"{subj} {focus['license']} 자격이 있어야 열 수 있어요. 자격 요건부터 확인하세요"
                f"(폐업 위험 {g}, 예상 연 폐업률 {rate}).")
    if high:
        crit = g == "고위험"                       # SB-06의 '창업 재검토 권장'과 같은 말을 리포트에도
        head = f"{area_label}에서 {josa(name, '은/는')}"
        # 업종 자체 위험은 높아도 이 지역 입지(같은 업종끼리)가 중간 이하이고 평균 매출이 손익분기를 넉넉히 넘는 경우
        lg = risk_grade(int(loc)) if ok(loc) else None
        dc = data_caveat(focus)
        good = (not short and ok(ratio) and ratio >= 1.15 and lg in ("낮음", "보통") and not focus.get("block") and not dc)
        tight = not short and ok(ratio) and ratio < 1.15      # 손익분기는 넘지만 여유가 적음(빠듯) — 카드의 '빠듯'과 같게
        if short:
            s1 = (f"{head} 폐업 위험이 매우 높고(예상 연 폐업률 {rate}) 평균 매출도 {bep}의 {_ra(times(ratio))} 창업 재검토를 권해요."
                  if crit else f"{head} 폐업 위험이 높고(예상 연 폐업률 {rate}) 평균 매출도 {bep}의 {_yeyo(times(ratio))}.")
        elif tight:
            s1 = (f"{head} 폐업 위험이 매우 높고(예상 연 폐업률 {rate}) 평균 매출도 {bep}의 {_ra(times(ratio))} 여유가 적어 "
                  "창업 재검토를 권해요." if crit
                  else f"{head} 폐업 위험이 높고(예상 연 폐업률 {rate}) 평균 매출도 {bep}의 {_ra(times(ratio))} 여유가 적어요.")
        elif crit:
            s1 = f"{head} 폐업 위험이 매우 높아(예상 연 폐업률 {rate}) 창업 재검토를 권해요."
        elif good:
            s1 = f"{head} 업종 특성상 폐업 위험이 높아요(예상 연 폐업률 {rate})."
        else:
            s1 = f"{head} 폐업 위험이 높아요(예상 연 폐업률 {rate})."
        if ok(loc) and loc >= 90:                  # 관심 업종이라 주의 업종(입지 위험 상위 10%)이어도 리포트가 그 사실을 말하게
            s1 += f" 같은 업종끼리 비교해도 이 지역 입지 위험이 매우 높아요({int(loc)})."
        if focus.get("block") and not short:
            # 손익분기를 못 냈어도(원가율 없는 업종) '평균 매출 < 월 고정비'·자격·수요 미검증은 위험도만큼 중요한 이유
            return f"{s1} {focus['block']}"
        bc = budget_caveat(focus)
        # 대안을 권해도 운영자금·매출 추정 문제는 빠뜨리지 않는다(둘 다 있으면 둘 다)
        also = "".join(f" 또 {c}" for c in (bc, dc) if c)
        # 손익분기를 못 냈으면(원가율을 모르는 업종) 위험이 높아도 원가율로 손익을 확인하라는 말을 빼지 않는다
        need_be = " 원가율을 넣어 손익분기도 확인하세요." if be is None and not focus.get("fixed_zero") else ""
        if good:
            if crit and (alt_s or area_s):
                # 매우 높으면 대안 비교가 먼저(입지·매출이 괜찮은 건 위 카드에 보인다)
                return f"{s1} {alt_s or area_s}{also}"
            facts = f"같은 업종끼리 비교한 입지 위험은 {LOC_WORD[lg]}({int(loc)})이고 평균 매출이 {bep}의 "
            if bc:                                # 예산·운영자금 문제가 있으면 '검토해 볼 만해요'라고 하지 않는다
                return f"{s1} 다만 {facts}{_yeyo(times(ratio))}. 또 {bc}"
            tail = "비용을 지키면 검토해 볼 만해요." if not crit else "그래도 한다면 비용을 지키고 운영자금부터 확보하세요."
            return f"{s1} 다만 {facts}{_ra(times(ratio))} {tail}"
        if alt_s or area_s:
            return f"{s1} {alt_s or area_s}{also}{need_be}"
        if bc or dc:
            return f"{s1} {bc or dc}" + (f" 또 {dc}" if bc and dc else "") + need_be
        return f"{s1}{need_be}" if need_be else f"{s1} 아래 체크리스트부터 점검하세요."
    if short:
        profit, max_f = be.get("profit_at_market_avg"), be.get("max_fixed_for_bep")
        fixed = (be or {}).get("monthly_fixed_cost")
        lim = won_floor_below(max_f, fixed) if ok(max_f) and ok(fixed) else max_f
        if owner > 0 and ok(profit) and profit + owner > 0:
            # 남는 돈과 목표가 반올림으로 같아 보여도(300만원 vs 300만원) 모자란 금액을 직접 밝힌다.
            # 모자란 금액은 체크리스트 '월 X 줄여야 함'과 같은 값(표시 금액끼리의 차이)을 쓴다
            gap = won_value(fixed) - lim if ok(max_f) and ok(fixed) else None
            if gap is not None and 0 < gap < owner:
                left, less = owner - gap, gap
            else:
                left, less = profit + owner, -profit
            s1 = (f"{subj} 평균 매출이면 가게에 월 {won(left)}이 남아 목표 월수입 {won(owner)}보다 월 {won(less)} 적어요"
                  f"(평균 매출은 필요 매출의 {times(ratio)}).")
            # 한도가 목표 월수입보다 작으면 다른 비용을 0원으로 줄여도 목표를 채울 수 없다 — 불가능한 방법을 권하지 않는다
            s2 = ("다른 비용을 모두 줄여도 평균 매출로는 목표 월수입을 채우기 어려워요 — 목표를 낮추거나 매출이 더 나는 업종·입지를 검토하세요."
                  if ok(max_f) and ok(lim) and lim < owner else
                  f"목표를 채우려면 월 고정비(목표 월수입 포함)를 {won(lim)} 이하로 낮추거나 목표를 조정하세요."
                  if ok(max_f) else "비용이나 목표 월수입을 조정해 보세요.")
        else:
            s1 = f"{subj} 평균 매출이 {bep}의 {_ra(times(ratio))} 지금 비용 구조로는 적자예요."
            s2 = ("다른 비용을 모두 줄여도 평균 매출로는 목표 월수입을 채우기 어려워요 — 목표를 낮추거나 매출이 더 나는 업종·입지를 검토하세요."
                  if owner > 0 and ok(max_f) and ok(lim) and lim < owner else
                  f"평균 매출로 버티려면 월 고정비{'(목표 월수입 포함)' if owner > 0 else ''}를 {won(lim)} 이하로 낮춰야 해요."
                  if ok(max_f) else "고정비를 줄일 방법부터 찾아보세요.")
        return f"{s1} {s2}"
    if focus.get("block"):                        # 평균 매출 < 월 고정비·수요 미검증이 입지 비교보다 먼저
        return f"{subj} {risk_is(g, rate, '지만')} {focus['block']}"
    if ok(loc) and loc >= 90:
        dc90 = data_caveat(focus)
        return (f"{subj} {risk_is(g, rate, '지만')}, 같은 업종끼리 비교하면 이 지역 입지 위험이 매우 높아요({int(loc)}). "
                + (area_s or "같은 업종 폐업이 잦은 이유(상권 이동·경쟁)를 현장에서 먼저 확인하세요.")
                + (f" 또 {dc90}" if dc90 else "")
                + (" 원가율을 넣어 손익분기도 확인하세요." if be is None and not focus.get("fixed_zero") else ""))
    pressure = be.get("cost_pressure") if be else None
    dc = data_caveat(focus)
    # 매출 추정이 흔들리면(비교할 구가 적음·대형 점포가 섞인 평균) 그 평균으로 '진입을 검토해 볼 만해요'라고 하지 않는다
    verdict = "" if dc else " 진입을 검토해 볼 만해요."
    if be is None and not focus.get("fixed_zero"):
        s = f"{subj} {risk_is(g, rate, '요')} 원가율을 넣어 손익분기를 확인한 뒤 결정하세요."
    elif ratio is None:                           # 월 고정비 0원: 원가율과 상관없이 손익분기 0원
        s = f"{subj} {risk_is(g, rate, '고')} 입력한 월 고정비가 0원이에요.{verdict}"
    elif pressure == "빠듯":
        s = (f"{subj} {risk_is(g, rate, '지만')} 평균 매출이 {bep}의 {_ra(times(ratio))} 여유가 적어요. "
             "비용을 더 줄일 수 있는지 먼저 점검하세요.")
    else:
        s = f"{subj} {risk_is(g, rate, '고')} 평균 매출이 {bep}의 {_yeyo(times(ratio))}.{verdict}"
    caveats = []                                  # 진입 검토 문장이어도 빠뜨리면 안 되는 단서(첫째는 '다만', 다음은 '또')
    over = focus.get("over_budget")
    if pressure != "빠듯" and be is not None:
        if ok(loc) and risk_grade(loc) == "높음":
            caveats.append(f"같은 업종끼리 비교한 입지 위험은 높은 편이에요({int(loc)}).")
    bc = budget_caveat(focus)
    if bc and ((ok(over) and over > 0) or (pressure != "빠듯" and be is not None)):
        caveats.append(bc)                        # 투자비 > 예산이면 늘, 운영비 부족은 '빠듯'(이미 비용 점검 권유)이 아닐 때
    if dc:
        caveats.append(dc)
    if focus.get("confidence") == "낮음":
        caveats.append("이 지역 점포가 적어 추정치는 참고용이에요.")
    first = " 하지만 " if (dc and be is not None and pressure != "빠듯") else " 다만 "   # 좋아 보이는 배율 뒤에 바로 단서
    for i, c in enumerate(caveats):
        s += (first if i == 0 else " 또 ") + c
    return s
