"""환경 설정. 모든 값은 환경변수로 덮어쓸 수 있다 (.env 파일 없이 동작하도록 기본값을 둔다)."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path):
    """backend/.env 의 KEY=VALUE 를 환경변수로(이미 설정된 값은 유지). 별도 패키지 없이 최소 구현."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


if os.environ.get("MIRI_NO_DOTENV") != "1":        # 테스트·검증 스크립트는 개발자 .env 영향을 받지 않게
    _load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _path(v: str) -> Path:
    p = Path(v)
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


def _db_url(v: str) -> str:
    """sqlite 상대 경로는 실행 위치가 아니라 backend/ 기준으로 해석."""
    prefix = "sqlite:///"
    if v.startswith(prefix) and not v.startswith("sqlite:////") and v[len(prefix):] not in ("", ":memory:"):
        return prefix + str(_path(v[len(prefix):]))
    return v


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _db_url(_env("MIRI_DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'miri.db'}")))
    data_dir: Path = field(default_factory=lambda: _path(_env("MIRI_DATA_DIR", str(ROOT_DIR / "data_raw"))))
    # 관리자 API(/admin/*)용 키. 비워 두면 관리자 API를 끈다(로그인이 없으므로 X-Admin-Key 헤더로만 확인)
    admin_key: str = field(default_factory=lambda: _env("MIRI_ADMIN_KEY", ""))
    cors_origins: list[str] = field(default_factory=lambda: _env(
        "MIRI_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    kakao_rest_key: str = field(default_factory=lambda: _env("KAKAO_REST_API_KEY", ""))
    frontend_dist: Path = field(default_factory=lambda: _path(_env("MIRI_FRONTEND_DIST", str(ROOT_DIR / "frontend" / "dist"))))

    def __post_init__(self):
        k = self.admin_key
        # 헤더(X-Admin-Key)로 보낼 수 있는 값만: 공백 없는 ASCII 인쇄 문자 32자 이상, 예시값 아님
        if k and (len(k) < 32 or not all("!" <= ch <= "~" for ch in k) or "change-me" in k.lower()):
            raise RuntimeError("MIRI_ADMIN_KEY는 공백 없는 영문·숫자·기호 32자 이상이어야 해요(예시값 불가). "
                               "python -c \"import secrets;print(secrets.token_urlsafe(48))\" 로 만든 값을 넣으세요")


settings = Settings()
