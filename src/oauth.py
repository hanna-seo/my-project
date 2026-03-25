"""ListeningMind OAuth 2.0 + PKCE 인증 흐름"""

import base64
import hashlib
import json
import os
import secrets

import requests

AUTH_SERVER   = "https://listeningmind-service-auth.ascentlab.io"
AUTHORIZE_URL = f"{AUTH_SERVER}/oauth/authorize"
TOKEN_URL     = f"{AUTH_SERVER}/oauth/token"
REGISTER_URL  = f"{AUTH_SERVER}/oauth/register"
REDIRECT_URI  = "http://localhost:5001/oauth/callback"

# 메모리 내 상태 저장 (단일 사용자 로컬 앱)
_state_store: dict = {}   # state → {"code_verifier": ..., "client_id": ...}
_client_cache: dict = {}  # {"client_id": ..., "client_secret": ...}


# ── PKCE 헬퍼 ────────────────────────────────────────────────────────
def _gen_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ── 동적 클라이언트 등록 ────────────────────────────────────────────
def _get_client() -> dict:
    """동적 클라이언트 등록 (최초 1회, 이후 캐시)"""
    if _client_cache:
        return _client_cache

    resp = requests.post(REGISTER_URL, json={
        "client_name": "Signal Finder",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _client_cache.update({"client_id": data["client_id"]})
    return _client_cache


# ── 인증 URL 생성 ────────────────────────────────────────────────────
def get_authorize_url() -> str:
    client = _get_client()
    verifier  = _gen_code_verifier()
    challenge = _code_challenge(verifier)
    state     = secrets.token_urlsafe(16)

    _state_store[state] = {
        "code_verifier": verifier,
        "client_id": client["client_id"],
    }

    params = "&".join([
        f"client_id={client['client_id']}",
        f"redirect_uri={REDIRECT_URI}",
        "response_type=code",
        "scope=mcp.access",
        f"state={state}",
        f"code_challenge={challenge}",
        "code_challenge_method=S256",
    ])
    return f"{AUTHORIZE_URL}?{params}"


# ── 코드 → 토큰 교환 ────────────────────────────────────────────────
def exchange_code(code: str, state: str) -> str:
    """인증 코드를 access token으로 교환하고 .env에 저장"""
    stored = _state_store.pop(state, None)
    if not stored:
        raise ValueError("유효하지 않은 state 파라미터")

    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": stored["client_id"],
        "code_verifier": stored["code_verifier"],
    }, timeout=10)
    resp.raise_for_status()

    token_data = resp.json()
    access_token = token_data["access_token"]

    # .env 파일에 토큰 저장
    _save_token_to_env(access_token)
    # 런타임 환경변수에도 즉시 적용
    os.environ["LISTENING_MIND_TOKEN"] = access_token

    # lm_tools 세션 갱신
    from src import lm_tools
    lm_tools._SESSION = None

    return access_token


def _save_token_to_env(token: str):
    """프로젝트 루트 .env 파일에 LISTENING_MIND_TOKEN 업데이트"""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("LISTENING_MIND_TOKEN="):
                    lines.append(f"LISTENING_MIND_TOKEN={token}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"LISTENING_MIND_TOKEN={token}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def is_authenticated() -> bool:
    return bool(os.getenv("LISTENING_MIND_TOKEN"))
