"""회차를 인스타그램에 게시 — <ep>/reel.mp4 가 있으면 릴스, 없으면 캐러셀.

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
        extra = "".join(f", {k} {err[k]}" for k in ("error_subcode", "type") if err.get(k))
        msg = err.get("error_user_msg") or err.get("error_user_title") or ""
        raise RuntimeError(f"{path}: HTTP {e.code} — {err.get('message', '')} (code {err.get('code')}{extra})"
                           + (f" / {msg}" if msg else ""))


class _Done(Exception):
    def __init__(self, post, info):
        self.post, self.info = post, info


def wait_ready(container_id, token, label, tries=30):
    for _ in range(tries):
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
    reel = os.path.exists(f"{ep_dir}/reel.mp4")
    images = sorted(glob.glob(f"{ep_dir}/final/*.jpg"))
    if not reel and not 2 <= len(images) <= 10:
        raise SystemExit(f"캐러셀 이미지는 2~10장이어야 함 (현재 {len(images)}장)")
    urls = [f"https://raw.githubusercontent.com/{REPO}/{sha}/{p}" for p in images]
    caption = script["caption"]
    if os.path.exists(f"{ep_dir}/credits.json"):  # 무료 사진 출처 표기 (Pixabay 이용 조건)
        users = []
        for c in json.load(open(f"{ep_dir}/credits.json", encoding="utf-8")).values():
            if c["user"] not in users:
                users.append(c["user"])
        caption += "\n\n📷 Photos: Pixabay (" + ", ".join(users) + ")"

    try:
        user_id = call("GET", "me", token, {"fields": "user_id"})["user_id"]
        if reel:
            vurl = f"https://raw.githubusercontent.com/{REPO}/{sha}/{ep_dir}/reel.mp4"
            c = call("POST", f"{user_id}/media", token, {
                "media_type": "REELS", "video_url": vurl, "caption": caption, "share_to_feed": "true",
                "cover_url": urls[0] if urls else "",
            })
            wait_ready(c["id"], token, "릴스 영상", tries=60)
            post = call("POST", f"{user_id}/media_publish", token, {"creation_id": c["id"]})
            info = call("GET", post["id"], token, {"fields": "permalink"})
            raise _Done(post, info)
        children = []
        for i, u in enumerate(urls, 1):
            c = call("POST", f"{user_id}/media", token, {"image_url": u, "is_carousel_item": "true"})
            wait_ready(c["id"], token, f"{i}번 이미지")
            children.append(c["id"])
        carousel = call("POST", f"{user_id}/media", token, {
            "media_type": "CAROUSEL", "children": ",".join(children), "caption": caption,
        })
        wait_ready(carousel["id"], token, "캐러셀")
        post = call("POST", f"{user_id}/media_publish", token, {"creation_id": carousel["id"]})
        info = call("GET", post["id"], token, {"fields": "permalink"})
    except _Done as d:
        post, info = d.post, d.info
    except RuntimeError as e:
        with open(f"{ep_dir}/publish_error.md", "w", encoding="utf-8") as f:
            f.write(f"# 게시 실패\n\n- 시각: {kst:%Y-%m-%d %H:%M KST}\n- 오류: {e}\n")
            if "access blocked" in str(e).lower() or "(code 190" in str(e):
                f.write("\n**원인: 인스타그램(Meta)이 이 토큰의 API 접근을 막았어요.** 코드 문제가 아니라 토큰을 새로 발급해야 해요.\n"
                        "1. 인스타그램 앱에서 보안 알림('본인이 맞나요?' 등)이 있으면 확인\n"
                        "2. developers.facebook.com → 내 앱 → Instagram → 'Instagram 로그인으로 API 설정' → 계정 옆 **토큰 생성**\n"
                        "3. GitHub 레포 Settings → Secrets → `INSTAGRAM_ACCESS_TOKEN` 값을 새 토큰으로 교체\n"
                        "4. 이 이슈에 `지금 게시` 댓글\n")
        print(f"❌ {e}")
        raise SystemExit(1)

    result = {"media_id": post["id"], "permalink": info.get("permalink"),
              "published_at": kst.isoformat(timespec="minutes"), "images": len(urls),
              "type": "reel" if reel else "carousel"}
    with open(f"{ep_dir}/published.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    if os.path.exists(f"{ep_dir}/publish_error.md"):
        os.remove(f"{ep_dir}/publish_error.md")
    print(f"✅ 게시 완료: {result['permalink']}")


if __name__ == "__main__":
    main()
