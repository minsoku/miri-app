"""요청 공통 의존성. 로그인이 없으므로 누구나 분석·위험도·손익분기·리포트를 쓸 수 있다.

저장 리포트(SB-09)는 계정 대신 '이 브라우저'로 구분한다: 화면이 리포트·저장 목록을 처음 부를 때 브라우저가 임의의 키(32바이트)를 만들어
localStorage에 두고, 리포트·저장 목록 요청에 `X-Device-Key` 헤더로 보낸다. 서버는 키의 SHA-256 해시만 저장·비교한다(키 자체는 남기지 않음).
"""
from __future__ import annotations
import hashlib
import hmac
import re
from fastapi import Header
from .errors import ApiError
from .settings import settings

DEVICE_HEADER = "X-Device-Key"
_DEVICE_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")     # base64url 32바이트 = 43자


def _device_hash(key: str | None) -> str | None:
    if key is None or key == "":
        return None
    if not _DEVICE_RE.fullmatch(key):
        raise ApiError(400, "INVALID_DEVICE_KEY", "이 브라우저의 저장 키가 올바르지 않아요. 새로고침한 뒤 다시 시도해 주세요")
    return hashlib.sha256(key.encode()).hexdigest()


def optional_device(x_device_key: str | None = Header(default=None, alias=DEVICE_HEADER,
                                                      description="이 브라우저의 저장 키(없으면 저장 여부를 알려 주지 않음)")) -> str | None:
    """리포트 조회처럼 누구나 쓰는 요청: 키가 있으면 '이 브라우저가 저장했는지'를 함께 알려 준다.
    형식이 틀린 키는 조용히 무시하지 않고 400(저장했는데 안 한 것처럼 보이지 않게)."""
    return _device_hash(x_device_key)


def require_device(x_device_key: str | None = Header(default=None, alias=DEVICE_HEADER,
                                                     description="이 브라우저의 저장 키(영문·숫자·-·_ 32~128자)")) -> str:
    h = _device_hash(x_device_key)
    if h is None:
        raise ApiError(400, "DEVICE_KEY_REQUIRED", "이 브라우저를 확인할 수 없어 저장 목록을 쓸 수 없어요. 새로고침한 뒤 다시 시도해 주세요")
    return h


def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key",
                                                   description="서버에 지정한 MIRI_ADMIN_KEY")) -> None:
    """관리자 API: 서버 환경변수 MIRI_ADMIN_KEY와 같은 값을 X-Admin-Key 헤더로 보내야 한다(지정하지 않은 서버는 꺼짐)."""
    if not settings.admin_key:
        raise ApiError(403, "ADMIN_DISABLED", "관리자 기능이 꺼져 있어요(서버에 MIRI_ADMIN_KEY를 지정해야 해요)")
    if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), settings.admin_key.encode()):
        raise ApiError(403, "FORBIDDEN", "관리자 키가 맞지 않아요")
