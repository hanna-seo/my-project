"""Jinja2 기반 HTML 리포트 생성기"""

import json
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _prepare_chart_data(keyword_info: dict, intents: dict) -> dict:
    """Chart.js에 전달할 데이터 구조 준비"""
    keywords_raw = keyword_info.get("keywords", keyword_info.get("data", []))

    # 1. 월별 검색량 추이 (상위 5개 키워드)
    top5 = keywords_raw[:5]
    monthly_labels = []
    monthly_datasets = []
    colors = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]

    for i, item in enumerate(top5):
        kw = item.get("keyword", f"키워드{i+1}")
        monthly = item.get("monthly_volume", [])
        if not monthly_labels and monthly:
            monthly_labels = [m.get("month", "") for m in monthly]
        values = [m.get("total", 0) for m in monthly]
        monthly_datasets.append({
            "label": kw,
            "data": values,
            "borderColor": colors[i % len(colors)],
            "backgroundColor": colors[i % len(colors)] + "20",
            "tension": 0.4,
            "fill": False,
        })

    # 2. 인텐트 분포 도넛 차트
    intent_counts = {"I": 0, "N": 0, "C": 0, "T": 0}
    intent_keywords_raw = intents.get("keywords", intents.get("data", []))
    for item in intent_keywords_raw:
        intent = str(item.get("intent") or item.get("intents") or "I")
        for key in intent_counts:
            if key in intent:
                intent_counts[key] += 1
                break
    intent_chart = {
        "labels": ["정보형(I)", "탐색형(N)", "비교형(C)", "구매형(T)"],
        "data": [intent_counts["I"], intent_counts["N"], intent_counts["C"], intent_counts["T"]],
        "colors": ["#6366f1", "#10b981", "#f59e0b", "#ef4444"],
    }

    # 3. 상위 키워드 검색량 바 차트 (상위 20개)
    top20 = keywords_raw[:20]
    top_keywords_chart = {
        "labels": [item.get("keyword", "") for item in top20],
        "data": [
            (item.get("ads_metrics") or item).get("volume_avg", 0)
            for item in top20
        ],
    }

    # 4. 인구통계 (첫 번째 키워드 기준)
    demo_chart = {"gender": {"labels": ["남성", "여성"], "data": [50, 50]}, "age": {"labels": [], "data": []}}
    if keywords_raw:
        first = keywords_raw[0]
        demo = first.get("demography") or first.get("ads_metrics") or first
        m_ratio = demo.get("m_gender_ratio", 50)
        f_ratio = demo.get("f_gender_ratio", 50)
        if m_ratio or f_ratio:
            demo_chart["gender"]["data"] = [m_ratio, f_ratio]
        age_keys = ["a13", "a20", "a25", "a30", "a40", "a50"]
        age_labels = ["13-19", "20-24", "25-29", "30-39", "40-49", "50+"]
        age_data = [demo.get(f"{k}_ratio", 0) for k in age_keys]
        if any(age_data):
            demo_chart["age"]["labels"] = age_labels
            demo_chart["age"]["data"] = age_data

    return {
        "monthly": {"labels": monthly_labels, "datasets": monthly_datasets},
        "intent": intent_chart,
        "top_keywords": top_keywords_chart,
        "demo": demo_chart,
    }


def _prepare_table_data(keyword_info: dict) -> list[dict]:
    """상세 테이블 데이터 준비"""
    rows = []
    keywords_raw = keyword_info.get("keywords", keyword_info.get("data", []))
    intent_map = {"I": "정보형", "N": "탐색형", "C": "비교형", "T": "구매형"}

    for item in keywords_raw[:50]:
        metrics = item.get("ads_metrics", item)
        intent_raw = str(item.get("intent") or item.get("intents") or "-")
        intent_label = intent_map.get(intent_raw[0] if intent_raw else "", intent_raw)
        trend = metrics.get("volume_trend", 0) or 0
        rows.append({
            "keyword": item.get("keyword", ""),
            "volume_avg": f"{int(metrics.get('volume_avg', 0) or 0):,}",
            "volume_trend": trend,
            "trend_label": f"+{trend:.1f}%" if trend > 0 else f"{trend:.1f}%",
            "trend_class": "positive" if trend > 0 else ("negative" if trend < 0 else "neutral"),
            "cpc": f"${metrics.get('cpc', 0) or 0:.2f}",
            "competition": metrics.get("competition", "-"),
            "intent": intent_label,
        })
    return rows


def generate(keyword: str, analysis: dict, keyword_info: dict, intents: dict, output_dir: str, date_str: str) -> str:
    """HTML 리포트 파일 생성 후 경로 반환"""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("report.html")

    chart_data = _prepare_chart_data(keyword_info, intents)
    table_data = _prepare_table_data(keyword_info)

    html = template.render(
        keyword=keyword,
        date=date_str,
        summary=analysis.get("summary", ""),
        signals=analysis.get("signals", []),
        opportunities=analysis.get("opportunities", []),
        threats=analysis.get("threats", []),
        intent_insight=analysis.get("intent_insight", ""),
        recommended_actions=analysis.get("recommended_actions", []),
        chart_data_json=json.dumps(chart_data, ensure_ascii=False),
        table_rows=table_data,
    )

    os.makedirs(output_dir, exist_ok=True)
    safe_keyword = keyword.replace(" ", "_").replace("/", "_")
    filename = f"{safe_keyword}_{date_str}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath
