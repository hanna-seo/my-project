#!/usr/bin/env python3
"""
HTML 리포트 저장 스크립트 (Claude Code 내부 호출용)
사용법: python save_report.py --input /tmp/signal_data.json
"""

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.report_generator import generate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="분석 데이터 JSON 파일 경로")
    parser.add_argument("--output", default="./reports", help="리포트 저장 디렉토리")
    parser.add_argument("--open", action="store_true", dest="open_browser", help="브라우저 자동 열기")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    filepath = generate(
        keyword=data["keyword"],
        analysis=data["analysis"],
        keyword_info=data.get("keyword_info", {}),
        intents=data.get("intents", {}),
        output_dir=args.output,
        date_str=data["date"],
    )

    print(f"REPORT_PATH:{os.path.abspath(filepath)}")

    if args.open_browser:
        webbrowser.open(f"file://{os.path.abspath(filepath)}")


if __name__ == "__main__":
    main()
