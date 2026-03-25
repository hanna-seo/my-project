"""Claude API 에이전트 루프 — 데이터 수집 + 시그널 분석 + 리포트 생성"""

import json
import os
from datetime import date
from typing import Generator

import anthropic

from src import lm_tools
from src.report_generator import generate as generate_report

# ── 프롬프트 ────────────────────────────────────────────────────────

COLLECTION_PROMPT = """당신은 시장 시그널 분석 전문가입니다.
'{keyword}' 키워드에 대해 다음 순서로 Listening Mind 데이터를 수집하세요:

1. cluster_finder (data_type='rels', gl='{country}', limit=50) → 연관 키워드 네트워크
2. intent_finder (keywords=['{keyword}'], gl='{country}', limit=100) → 인텐트별 키워드
3. keyword_info (상위 연관 키워드 최대 20개 포함, gl='{country}', data_type='all') → 검색량/트렌드/인구통계
4. path_finder (keyword='{keyword}', gl='{country}', limit=300) → 소비자 탐색 경로

모든 데이터 수집이 완료되면, 수집한 데이터를 바탕으로 반드시 아래 JSON 형식으로만 응답하세요.
다른 텍스트는 포함하지 마세요. 코드블록(```)도 쓰지 마세요.

{{
  "summary": "한 문장으로 '{keyword}' 시장의 현재 상황 요약",
  "signals": [
    {{
      "title": "시그널 제목 (10자 이내)",
      "body": "시그널 설명 (2~3문장, 과거→현재 변화 패턴)",
      "evidence": "근거 수치 (예: '메디큐브' 검색량 +68% 증가)",
      "type": "opportunity 또는 threat 또는 trend"
    }}
  ],
  "opportunities": ["기회 키워드1", "기회 키워드2", "기회 키워드3"],
  "threats": ["위협 키워드1", "위협 키워드2"],
  "intent_insight": "소비자 인텐트 패턴에 대한 1~2문장 해석",
  "recommended_actions": ["액션1", "액션2", "액션3"]
}}

규칙:
- 반드시 수집된 데이터의 수치(검색량, 트렌드%)를 근거로 서술하세요.
- 데이터 부족 항목은 '데이터 부족'으로 표기하세요.
- signals 3~5개, opportunities 2~5개, threats 1~3개."""

# ── 진행 단계 메시지 ─────────────────────────────────────────────────
_STEP_MSGS = {
    "cluster_finder": ("연관 키워드 네트워크 수집 중...", 20),
    "intent_finder":  ("인텐트별 키워드 수집 중...",      40),
    "keyword_info":   ("검색량 · 트렌드 데이터 수집 중...", 60),
    "path_finder":    ("소비자 탐색 경로 분석 중...",      75),
}


def _evt(type_: str, **kwargs) -> str:
    return json.dumps({"type": type_, **kwargs}, ensure_ascii=False)


def run(keyword: str, country: str = "kr") -> Generator[str, None, None]:
    """SSE 이벤트 문자열을 yield하는 제너레이터"""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    messages = [{"role": "user", "content": COLLECTION_PROMPT.format(keyword=keyword, country=country)}]

    # ── 수집된 원본 데이터 저장 ──────────────────────────────────────
    raw_data: dict = {}

    yield _evt("progress", msg="분석을 시작합니다...", pct=5)

    # ── 에이전트 루프 ────────────────────────────────────────────────
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=lm_tools.TOOL_SCHEMAS,
            messages=messages,
        )

        # assistant 메시지 축적
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # 최종 텍스트 응답 파싱
            final_text = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            ).strip()
            break

        if response.stop_reason != "tool_use":
            yield _evt("error", msg=f"예상치 못한 stop_reason: {response.stop_reason}")
            return

        # ── 툴 실행 ──────────────────────────────────────────────────
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_inputs = block.input

            # 진행 이벤트
            msg, pct = _STEP_MSGS.get(tool_name, ("데이터 수집 중...", 50))
            yield _evt("progress", msg=msg, pct=pct)

            result = lm_tools.execute_tool(tool_name, tool_inputs)
            raw_data[tool_name] = result

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        messages.append({"role": "user", "content": tool_results})

    # ── AI 분석 결과 파싱 ────────────────────────────────────────────
    yield _evt("progress", msg="AI 시그널 분석 완료. 리포트 생성 중...", pct=90)

    try:
        analysis = json.loads(final_text)
    except json.JSONDecodeError:
        # JSON 블록 추출 시도
        import re
        m = re.search(r"\{[\s\S]+\}", final_text)
        if m:
            analysis = json.loads(m.group())
        else:
            analysis = {
                "summary": f"'{keyword}' 분석 완료 (JSON 파싱 실패)",
                "signals": [], "opportunities": [], "threats": [],
                "intent_insight": "", "recommended_actions": [],
            }

    # ── HTML 리포트 생성 ─────────────────────────────────────────────
    today = date.today().strftime("%Y-%m-%d")
    filepath = generate_report(
        keyword=keyword,
        analysis=analysis,
        keyword_info=raw_data.get("keyword_info", {}),
        intents={"keywords": [{"keyword": k, "intent": "I"} for k in raw_data.get("intent_finder", {}).get("data", [])]},
        output_dir="reports",
        date_str=today,
    )

    safe_kw = keyword.replace(" ", "_").replace("/", "_")
    report_url = f"/reports/{safe_kw}_{today}.html"

    yield _evt("done", report_url=report_url, keyword=keyword)
