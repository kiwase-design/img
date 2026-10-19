"""Instagram 토큰 점검 (게시하지 않음).

- 토큰으로 계정 정보 조회 (graph.instagram.com/me)
- 게시용 이미지 URL이 외부에서 열리는지 확인
결과는 checks/instagram_check.md 에 기록. 토큰 값은 출력하지 않는다.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

OUT = "checks/instagram_check.md"
REPO = os.environ.get("GITHUB_REPOSITORY", "kiwase-design/img")
SAMPLE = f"https://raw.githubusercontent.com/{REPO}/main/episodes/ep001/final/01.png"


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def main():
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    lines = ["# Instagram 점검 결과", "", f"- 실행 시각: {kst}"]
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()

    if not token:
        lines.append("- 토큰: ❌ `INSTAGRAM_ACCESS_TOKEN` 시크릿 없음")
    else:
        status, data = get(
            "https://graph.instagram.com/me?fields=user_id,username,account_type,media_count"
            f"&access_token={token}"
        )
        if status == 200:
            lines.append(
                f"- 토큰: ✅ 정상 — @{data.get('username')} "
                f"(유형: {data.get('account_type')}, 게시물 {data.get('media_count')}개)"
            )
        else:
            err = data.get("error", {})
            lines.append(f"- 토큰: ❌ HTTP {status} — {err.get('message', '')} (code {err.get('code')})")

    status, _ = get(SAMPLE)
    if status == 200:
        lines.append("- 이미지 공개 URL: ✅ 외부에서 열림")
    else:
        lines.append(f"- 이미지 공개 URL: ❌ HTTP {status} (레포가 비공개라 인스타가 이미지를 가져갈 수 없음)")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
