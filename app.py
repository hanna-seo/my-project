"""Signal Finder — Flask 웹 서버 (API 키 불필요 버전)"""

import glob
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, render_template, send_from_directory, request, jsonify

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src import oauth

app = Flask(__name__)
REPORTS_DIR = Path(__file__).parent / "reports"


# ── 유틸 ──────────────────────────────────────────────────────────────
def _safe_keyword(keyword: str) -> str:
    return keyword.replace(" ", "_").replace("/", "_")


def _find_report(keyword: str) -> str | None:
    """키워드에 해당하는 가장 최근 리포트 파일명 반환"""
    safe = _safe_keyword(keyword)
    pattern = str(REPORTS_DIR / f"{safe}_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    return Path(files[0]).name if files else None


def _list_reports() -> list[dict]:
    """reports/ 디렉토리의 모든 리포트 목록 반환"""
    files = sorted(REPORTS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        import re
        m = re.match(r"^(.+?)_(\d{4}-\d{2}-\d{2})$", f.stem)
        if m:
            keyword = m.group(1).replace("_", " ")
            date_str = m.group(2)
        else:
            keyword = f.stem.replace("_", " ")
            date_str = ""
        result.append({
            "filename": f.name,
            "keyword": keyword,
            "date": date_str,
            "url": f"/reports/{f.name}",
            "mtime": f.stat().st_mtime,
        })
    return result


# ── 라우트 ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    reports = _list_reports()
    return render_template("index.html",
                           authenticated=oauth.is_authenticated(),
                           reports=reports)


@app.route("/oauth/login")
def oauth_login():
    from flask import redirect
    return redirect(oauth.get_authorize_url())


@app.route("/oauth/callback")
def oauth_callback():
    from flask import redirect
    code  = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")
    if error:
        return render_template("index.html", authenticated=False,
                               auth_error=f"로그인 실패: {error}", reports=[])
    try:
        oauth.exchange_code(code, state)
        return redirect("/")
    except Exception as e:
        return render_template("index.html", authenticated=False,
                               auth_error=str(e), reports=[])


@app.route("/api/analyze")
def analyze():
    """SSE: 키워드에 해당하는 리포트 파일이 생길 때까지 폴링"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return {"error": "키워드를 입력해주세요."}, 400

    requested_at = time.time()
    safe = _safe_keyword(keyword)
    today = date.today().strftime("%Y-%m-%d")
    target = REPORTS_DIR / f"{safe}_{today}.html"

    def stream():
        yield f"data: {json.dumps({'type':'waiting', 'keyword': keyword}, ensure_ascii=False)}\n\n"

        deadline = requested_at + 600  # 최대 10분 대기
        while time.time() < deadline:
            # 오늘 날짜 파일 우선 확인
            if target.exists() and target.stat().st_mtime >= requested_at:
                url = f"/reports/{target.name}"
                yield f"data: {json.dumps({'type':'done','report_url':url,'keyword':keyword}, ensure_ascii=False)}\n\n"
                return
            # 키워드 일치하는 최신 파일도 확인 (날짜 무관)
            found = _find_report(keyword)
            if found:
                fpath = REPORTS_DIR / found
                if fpath.stat().st_mtime >= requested_at:
                    url = f"/reports/{found}"
                    yield f"data: {json.dumps({'type':'done','report_url':url,'keyword':keyword}, ensure_ascii=False)}\n\n"
                    return
            time.sleep(2)

        yield f"data: {json.dumps({'type':'timeout','msg':'10분 초과 — 채팅창에서 분석을 다시 요청해주세요.'}, ensure_ascii=False)}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/reports")
def api_reports():
    return jsonify(_list_reports())


@app.route("/reports/<path:filename>")
def serve_report(filename):
    return send_from_directory("reports", filename)


if __name__ == "__main__":
    REPORTS_DIR.mkdir(exist_ok=True)
    print("\n  Signal Finder 서버 시작")
    print("  → http://localhost:5001\n")
    app.run(debug=True, threaded=True, port=5001)
