"""Listening Mind 툴 정의 + MCP 프로토콜 실행"""

import json
import os

import requests

_BASE_URL = None
_TOKEN = None
_SESSION = None
_MCP_SESSION_ID = None


def _init_mcp_session() -> tuple[requests.Session, str]:
    """MCP 세션 초기화 후 (requests.Session, mcp-session-id) 반환"""
    global _BASE_URL, _TOKEN, _SESSION, _MCP_SESSION_ID

    _BASE_URL = os.getenv("LISTENING_MIND_API_URL", "").rstrip("/")
    _TOKEN = os.getenv("LISTENING_MIND_TOKEN", "")

    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })

    # initialize
    resp = sess.post(f"{_BASE_URL}/", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Signal Finder", "version": "1.0"},
        },
    }, timeout=10)
    resp.raise_for_status()
    mcp_sid = resp.headers.get("mcp-session-id", "")

    # initialized notification
    sess.headers.update({"mcp-session-id": mcp_sid})
    sess.post(f"{_BASE_URL}/", json={
        "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
    }, timeout=5)

    _SESSION = sess
    _MCP_SESSION_ID = mcp_sid
    return sess, mcp_sid


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _init_mcp_session()
    return _SESSION


def _parse_sse(response: requests.Response) -> dict:
    """SSE 스트림에서 첫 번째 data 이벤트를 파싱해 반환"""
    buf = ""
    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
        buf += chunk
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    pass
    return {}


def execute_tool(name: str, inputs: dict) -> dict:
    """툴 이름과 입력을 받아 MCP tools/call을 호출하고 결과 반환"""
    sess = _get_session()
    try:
        resp = sess.post(f"{_BASE_URL}/", json={
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": name, "arguments": inputs},
        }, timeout=30, stream=True)
        resp.raise_for_status()

        data = _parse_sse(resp)
        if "error" in data:
            return {"error": data["error"]}

        # result.content 는 [{type: "text", text: "..."}] 형태
        content = data.get("result", {}).get("content", [])
        for item in content:
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except json.JSONDecodeError:
                    return {"raw": item["text"]}
        return {"raw": content}

    except requests.exceptions.HTTPError as e:
        # 세션 만료 시 재시도
        if e.response is not None and e.response.status_code in (400, 401):
            global _SESSION
            _SESSION = None
            return execute_tool(name, inputs)
        return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text[:300]}
    except Exception as e:
        return {"error": str(e)}


# ── Anthropic tool_use 스키마 정의 ───────────────────────────────────
TOOL_SCHEMAS = [
    {
        "name": "cluster_finder",
        "description": (
            "키워드의 연관 키워드 네트워크와 소비자 커뮤니티 인식을 분석합니다. "
            "data_type='rels'이면 연관 키워드 관계, 'communities'이면 소비자 인식 커뮤니티를 반환합니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "분석할 키워드"},
                "gl":      {"type": "string", "enum": ["kr", "jp", "us"], "description": "국가 코드"},
                "data_type": {"type": "string", "enum": ["communities", "rels", "all"], "default": "rels"},
                "hop":    {"type": "integer", "default": 2, "minimum": 1, "maximum": 3},
                "limit":  {"type": "integer", "default": 100},
                "time_point": {"type": "string", "enum": ["curr", "3m", "6m", "9m", "12m"], "default": "curr"},
            },
            "required": ["keyword", "gl"],
        },
    },
    {
        "name": "intent_finder",
        "description": "키워드의 연관 키워드 리스트를 월 평균 검색량 순으로 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "키워드 목록"},
                "gl":       {"type": "string", "enum": ["kr", "jp", "us"]},
                "limit":    {"type": "integer", "default": 100},
                "sort":     {"type": "string", "enum": ["volume_avg", "volume_total", "volume_trend", "cpc"], "default": "volume_avg"},
                "volume_threshold": {"type": "integer", "default": 100},
            },
            "required": ["keywords", "gl"],
        },
    },
    {
        "name": "keyword_info",
        "description": (
            "키워드별 검색량, 트렌드, CPC, 경쟁도, 월별 검색량, 소비자 인텐트, 인구통계를 반환합니다. "
            "data_type='all'이면 모든 정보를 반환합니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords":  {"type": "array", "items": {"type": "string"}, "description": "키워드 목록 (최대 30개 권장)"},
                "gl":        {"type": "string", "enum": ["kr", "jp", "us"]},
                "data_type": {"type": "string", "enum": ["ads_metrics", "ads_info", "all"], "default": "all"},
            },
            "required": ["keywords", "gl"],
        },
    },
    {
        "name": "path_finder",
        "description": "소비자가 해당 키워드에 도달하기까지의 검색 탐색 경로를 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword":    {"type": "string"},
                "gl":         {"type": "string", "enum": ["kr", "jp", "us"]},
                "limit":      {"type": "integer", "default": 300},
                "time_point": {"type": "string", "enum": ["curr", "3m", "6m", "9m", "12m"], "default": "curr"},
            },
            "required": ["keyword", "gl"],
        },
    },
]
