"""회차를 인스타그램 캐러셀로 게시.

사용법: python scripts/publish_instagram.py episodes/ep001 <commit_sha>

- <ep>/final/NN.jpg 를 GitHub raw URL(커밋 SHA 고정)로 인스타에 전달
- 이미 게시된 회차(<ep>/published.json 존재)는 다시 올리지 않음
- 결과는 <ep>/published.json 또는 <ep>/publish_error.md 에 기록
"""
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://graph.instagram.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "kiwase-design/img")


def call(method, path, token, params=None):
    params = dict(params or {}, access_token=token)
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    if method == "GET":
        url, data = f"{url}?{data.decode()}", None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except Exception:
            err = {}
        raise RuntimeError(f"{path}: HTTP {e.code} — {err.get('message', '')} (code {err.get('code')})")


def wait_ready(container_id, token, label):
    for _ in range(30):
        status = call("GET", container_id, token, {"fields": "status_code,status"})
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{label} 처리 실패: {status.get('status')}")
        time.sleep(5)
    raise RuntimeError(f"{label} 처리 시간 초과")


def main():
    ep_dir, sha = sys.argv[1].rstrip("/"), sys.argv[2]
    kst = datetime.now(timezone(timedelta(hours=9)))
    if os.path.exists(f"{ep_dir}/published.json"):
        print(f"{ep_dir}: 이미 게시됨 — 건너뜀")
        return

    token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
    script = json.load(open(f"{ep_dir}/script.json", encoding="utf-8"))
    images = sorted(glob.glob(f"{ep_dir}/final/*.jpg"))
    if not 2 <= len(images) <= 10:
        raise SystemExit(f"캐러셀 이미지는 2~10장이어야 함 (현재 {len(images)}장)")
    urls = [f"https://raw.githubusercontent.com/{REPO}/{sha}/{p}" for p in images]

    try:
        user_id = call("GET", "me", token, {"fields": "user_id"})["user_id"]
        children = []
        for i, u in enumerate(urls, 1):
            c = call("POST", f"{user_id}/media", token, {"image_url": u, "is_carousel_item": "true"})
            wait_ready(c["id"], token, f"{i}번 이미지")
            children.append(c["id"])
        carousel = call("POST", f"{user_id}/media", token, {
            "media_type": "CAROUSEL", "children": ",".join(children), "caption": script["caption"],
        })
        wait_ready(carousel["id"], token, "캐러셀")
        post = call("POST", f"{user_id}/media_publish", token, {"creation_id": carousel["id"]})
        info = call("GET", post["id"], token, {"fields": "permalink"})
    except RuntimeError as e:
        with open(f"{ep_dir}/publish_error.md", "w", encoding="utf-8") as f:
            f.write(f"# 게시 실패\n\n- 시각: {kst:%Y-%m-%d %H:%M KST}\n- 오류: {e}\n")
        print(f"❌ {e}")
        raise SystemExit(1)

    result = {"media_id": post["id"], "permalink": info.get("permalink"),
              "published_at": kst.isoformat(timespec="minutes"), "images": len(urls)}
    with open(f"{ep_dir}/published.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    if os.path.exists(f"{ep_dir}/publish_error.md"):
        os.remove(f"{ep_dir}/publish_error.md")
    print(f"✅ 게시 완료: {result['permalink']}")


if __name__ == "__main__":
    main()
