"""연재 자동화 봇 — GitHub Actions 에서 실행.

  python scripts/webtoon_bot.py generate   # (매일 12시) 다음 회차 생성 → 승인 요청 이슈
  python scripts/webtoon_bot.py publish    # (매일 20:50) 승인된 회차 게시
  python scripts/webtoon_bot.py command    # 이슈 댓글 명령 처리
  python scripts/webtoon_bot.py refresh    # (매월) 인스타 토큰 갱신

회차 상태 (episodes/epNNN/ 안의 파일로 표시):
  script.json + final/  → 승인 대기
  APPROVED              → 승인됨 (20:50 게시)
  published.json        → 게시 완료
  SKIPPED               → 건너뜀
연재 on/off 는 config/state.json 의 enabled.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

REPO = os.environ.get("GITHUB_REPOSITORY", "kiwase-design/img")
STATE = "config/state.json"
KST = timezone(timedelta(hours=9))
RAW = f"https://raw.githubusercontent.com/{REPO}"
ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}
POST_HOUR, POST_MIN = 20, 50  # 매일 게시 시각 (KST)

HELP = """**댓글 명령어**
| 명령 | 동작 |
|---|---|
| `승인` | 오늘 저녁 8시 50분에 게시 |
| `지금 게시` | 바로 게시 |
| `그림 다시` | 같은 대본으로 사진만 다시 |
| `다시` | 같은 상황, 새 대화로 처음부터 다시 |
| `건너뛰기` | 이 회차 버리기 |
| `주제 호텔 체크인` | 승인 이슈에서: 이 편을 그 상황으로 다시 / 관리 이슈에서: 다음 편 상황 지정 |
| `중단` / `시작` / `상태` | 연재 멈춤 / 재개 / 현재 상태 |"""


# ---------- 공통 ----------

def now():
    return datetime.now(KST)


def sh(*cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def git_push(msg):
    sh("git", "add", "-A", "episodes", "config")
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    sh("git", "commit", "-q", "-m", f"{msg} [skip ci]")
    sh("git", "pull", "-q", "--rebase")
    sh("git", "push", "-q")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def gh(method, path, body=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read()
        return json.loads(txt) if txt else {}


def comment(issue, text):
    gh("POST", f"issues/{issue}/comments", {"body": text})


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"enabled": True}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")


def control_issue():
    st = load_state()
    if st.get("control_issue"):
        return st["control_issue"]
    issue = gh("POST", "issues", {
        "title": f"🎛 연재 관리 ({json.load(open('config/series.json', encoding='utf-8'))['title']})", "labels": ["control"],
        "body": "이 이슈에 댓글로 `중단`, `시작`, `상태` 를 남기면 연재를 제어할 수 있어요.\n\n" + HELP,
    })["number"]
    st["control_issue"] = issue
    save_state(st)
    git_push("관리 이슈 생성")
    return issue


def episodes():
    return sorted(d for d in glob.glob("episodes/ep*") if os.path.isdir(d))


def status(d):
    if os.path.exists(f"{d}/published.json"):
        return "published"
    if os.path.exists(f"{d}/SKIPPED"):
        return "skipped"
    if os.path.exists(f"{d}/APPROVED"):
        return "approved"
    if glob.glob(f"{d}/final/*.png"):
        return "pending"
    return "draft"


def ep_title(d):
    s = json.load(open(f"{d}/script.json", encoding="utf-8"))
    return f"#{s['episode']} 「{s['title']}」"


def issue_of(d):
    p = f"{d}/issue.json"
    return json.load(open(p))["number"] if os.path.exists(p) else None


def ep_from_issue(number):
    for d in episodes():
        if issue_of(d) == number:
            return d
    return None


def render(d, force=False):
    args = ["python", "scripts/render_episode.py", d] + (["--force"] if force else [])
    sh(*args)
    finals = glob.glob(f"{d}/final/*.png")
    if len(finals) < 4:
        report = open(f"{d}/report.md", encoding="utf-8").read() if os.path.exists(f"{d}/report.md") else ""
        raise RuntimeError(f"그림 생성 실패\n\n{report}")


def preview_md(d, sha):
    s = json.load(open(f"{d}/script.json", encoding="utf-8"))
    imgs = " ".join(
        f'<img src="{RAW}/{sha}/{p}" width="200">' for p in sorted(glob.glob(f"{d}/final/*.png"))
    )
    lines = []
    for p in s["panels"]:
        for x in p["dialogues"]:
            who = "🙋" if x["speaker"] != "staff" else "🧑‍💼"
            lines.append(f"{who} {x.get('en', x.get('text', ''))}  \n   ↳ {x.get('ko', '')}")
    topic = f"**상황**: {s['topic']}\n\n" if s.get("topic") else ""
    return f"{topic}{imgs}\n\n**대화**\n" + "\n".join(lines) + f"\n\n**캡션**\n```\n{s['caption']}\n```"


# ---------- 생성 ----------

def generate(reason="매일 자동 생성"):
    control_issue()  # 관리 이슈가 없으면 만들어 둠
    st = load_state()
    if not st.get("enabled", True):
        print("연재 중단 상태 — 생성하지 않음")
        return
    waiting = [d for d in episodes() if status(d) in ("pending", "approved", "draft")]
    if waiting:
        print(f"아직 처리 안 된 회차가 있어 새로 만들지 않음: {waiting}")
        return
    nums = [int(re.search(r"ep(\d+)", d).group(1)) for d in episodes()]
    d = f"episodes/ep{(max(nums) + 1 if nums else 1):03d}"
    make_episode(d, reason)


def make_episode(d, reason):
    try:
        sh("python", "scripts/write_episode.py", d)
        render(d)
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)  # 다음 실행 때 다시 시도할 수 있게 정리
        comment(control_issue(), f"⚠️ `{d}` 생성 중 오류가 났어요. 다음 생성 시간에 다시 시도해요.\n\n```\n{e}\n```")
        raise
    sha = git_push(f"{d} 생성")
    issue = gh("POST", "issues", {
        "title": f"📝 {ep_title(d)} 승인 대기", "labels": ["episode"],
        "body": f"{reason} — {now():%m월 %d일 %H:%M}\n\n{preview_md(d, sha)}\n\n---\n{HELP}",
    })["number"]
    with open(f"{d}/issue.json", "w") as f:
        json.dump({"number": issue}, f)
    git_push(f"{d} 승인 이슈 #{issue}")


# ---------- 게시 ----------

def publish(only=None):
    st = load_state()
    if not st.get("enabled", True):
        print("연재 중단 상태 — 게시하지 않음")
        return
    targets = [only] if only else [d for d in episodes() if status(d) == "approved"][:1]
    if not only and not targets:
        print("게시할 승인 회차 없음")
        return
    if not only and os.environ.get("WAIT_UNTIL_9PM"):
        # GitHub 예약 실행이 늦는 걸 대비해 일찍 시작하고, 정확히 20:50까지 기다렸다가 게시
        nine = now().replace(hour=POST_HOUR, minute=POST_MIN, second=0, microsecond=0)
        wait = (nine - now()).total_seconds()
        if 0 < wait < 3600:
            print(f"{POST_HOUR}:{POST_MIN:02d}까지 {int(wait)}초 대기")
            import time
            time.sleep(wait)
    for d in targets:
        from PIL import Image
        for p in sorted(glob.glob(f"{d}/final/*.png")):
            Image.open(p).convert("RGB").save(p[:-4] + ".jpg", quality=92)
        sha = git_push(f"{d} 게시용 JPG")
        res = subprocess.run(["python", "scripts/publish_instagram.py", d, sha])
        git_push(f"{d} 게시 결과")
        issue = issue_of(d)
        if res.returncode == 0 and os.path.exists(f"{d}/published.json"):
            link = json.load(open(f"{d}/published.json"))["permalink"]
            if issue:
                comment(issue, f"✅ 게시 완료! {link}")
                gh("PATCH", f"issues/{issue}", {"state": "closed"})
        else:
            err = open(f"{d}/publish_error.md", encoding="utf-8").read() if os.path.exists(f"{d}/publish_error.md") else ""
            comment(issue or control_issue(), f"❌ 게시 실패\n\n{err}")
            raise SystemExit(1)


# ---------- 댓글 명령 ----------

def command():
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
    c, issue = ev["comment"], ev["issue"]
    if c["author_association"] not in ALLOWED or c["user"]["type"] == "Bot":
        return
    text = re.sub(r"\s+", " ", c["body"]).strip()
    n = issue["number"]
    st = load_state()

    if text in ("중단", "멈춤", "정지"):
        st["enabled"] = False
        save_state(st)
        git_push("연재 중단")
        comment(n, "⏸ 연재를 중단했어요. 자동 생성과 게시가 모두 멈춥니다. 다시 하려면 `시작`.")
        return
    if text in ("시작", "다시 시작", "재개"):
        st["enabled"] = True
        save_state(st)
        git_push("연재 재개")
        comment(n, "▶️ 연재를 다시 시작했어요. 매일 12시 생성 → 승인 → 저녁 8시 50분 게시.")
        if not [d for d in episodes() if status(d) in ("pending", "approved", "draft")]:
            generate("재개하면서 바로 생성")
        return
    if text == "상태":
        rows = [f"| {os.path.basename(d)} | {status(d)} |" for d in episodes()[-8:]]
        comment(n, f"연재: **{'진행 중 ▶️' if st.get('enabled', True) else '중단됨 ⏸'}**\n\n"
                   "| 회차 | 상태 |\n|---|---|\n" + "\n".join(rows))
        return

    d = ep_from_issue(n)
    if text.startswith("주제 ") and not d:
        city = text[3:].strip()
        open("config/next_topic.txt", "w", encoding="utf-8").write(city)
        git_push(f"다음 주제 지정: {city}")
        comment(n, f"📍 다음 편은 **{city}** 상황으로 만들게요.")
        return
    if not d:
        if text in ("승인", "지금 게시", "다시", "그림 다시", "건너뛰기", "도움말"):
            comment(n, "이 명령은 회차 승인 이슈에서만 쓸 수 있어요.\n\n" + HELP)
        return
    if status(d) in ("published", "skipped"):
        comment(n, "이미 처리된 회차예요.")
        return

    if text == "승인":
        open(f"{d}/APPROVED", "w").write(now().isoformat())
        git_push(f"{d} 승인")
        t = now()
        mins = t.hour * 60 + t.minute
        if mins < POST_HOUR * 60 + POST_MIN:
            msg = "**오늘 저녁 8시 50분**에 게시돼요."
        elif mins < 21 * 60 + 20:
            msg = "게시 시간이 지나서 **잠시 후(21:23 전후)** 게시돼요. 바로 올리려면 `지금 게시`."
        else:
            msg = "오늘 게시 시간이 지나서 **내일 저녁 8시 50분**에 게시돼요. 바로 올리려면 `지금 게시`."
        comment(n, "👍 승인됐어요. " + msg)
    elif text == "지금 게시":
        open(f"{d}/APPROVED", "w").write(now().isoformat())
        git_push(f"{d} 승인")
        comment(n, "🚀 바로 게시할게요…")
        publish(only=d)
    elif text == "그림 다시":
        comment(n, "🎨 같은 대본으로 그림을 다시 그릴게요 (몇 분 걸려요)…")
        for sub in ("raw", "final"):
            shutil.rmtree(f"{d}/{sub}", ignore_errors=True)
        render(d)
        sha = git_push(f"{d} 그림 다시")
        comment(n, "새 그림이에요. 괜찮으면 `승인`.\n\n" + preview_md(d, sha))
    elif text == "다시":
        comment(n, "🔄 새 이야기로 처음부터 다시 만들게요. 새 승인 이슈가 열려요.")
        gh("PATCH", f"issues/{n}", {"state": "closed", "state_reason": "not_planned"})
        shutil.rmtree(d)
        git_push(f"{d} 폐기 후 재생성")
        make_episode(d, "다시 요청으로 재생성")
    elif text == "건너뛰기":
        open(f"{d}/SKIPPED", "w").write(now().isoformat())
        git_push(f"{d} 건너뜀")
        comment(n, "🗑 이 회차는 건너뛸게요. 다음 회차는 내일 12시에 만들어져요.")
        gh("PATCH", f"issues/{n}", {"state": "closed", "state_reason": "not_planned"})
    elif text.startswith("주제 "):
        city = text[3:].strip()
        comment(n, f"📍 이 편을 **{city}** 상황으로 처음부터 다시 만들게요. 새 승인 이슈가 열려요.")
        gh("PATCH", f"issues/{n}", {"state": "closed", "state_reason": "not_planned"})
        shutil.rmtree(d)
        open("config/next_topic.txt", "w", encoding="utf-8").write(city)
        git_push(f"{d} 주제 변경 → {city}")
        make_episode(d, f"주제 변경 요청 ({city})")
    elif text == "도움말":
        comment(n, HELP)


# ---------- 토큰 갱신 ----------

def refresh():
    token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
    url = ("https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token"
           f"&access_token={token}")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        comment(control_issue(), f"⚠️ 인스타 토큰 갱신 실패 (HTTP {e.code}). 토큰을 새로 발급해 Secrets에 저장해주세요.")
        raise SystemExit(1)
    days = int(data.get("expires_in", 0)) // 86400
    new = data.get("access_token", "")
    if new and new != token:
        if os.environ.get("GH_PAT"):
            subprocess.run(["gh", "secret", "set", "INSTAGRAM_ACCESS_TOKEN", "--body", new, "-R", REPO],
                           check=True, env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]})
            print(f"토큰 갱신 및 저장 완료 ({days}일 유효)")
        else:
            comment(control_issue(), "⚠️ 인스타 토큰이 새 값으로 바뀌었는데 자동 저장 권한(GH_PAT)이 없어요. Claude에게 알려주세요.")
    else:
        print(f"토큰 갱신 완료 ({days}일 유효)")


def rerender():
    """config/trigger.json 의 episode 를 다시 렌더링 (raw 가 없는 컷만 새로 그림) 후 승인 이슈에 수정본 게시."""
    d = json.load(open("config/trigger.json", encoding="utf-8"))["episode"].rstrip("/")
    for p in glob.glob(f"{d}/final/*"):
        os.remove(p)
    render(d)
    sha = git_push(f"{d} 수정본 렌더링")
    issue = issue_of(d)
    if issue:
        comment(issue, "✏️ 수정본이에요. 괜찮으면 `승인`.\n\n" + preview_md(d, sha))


if __name__ == "__main__":
    action = sys.argv[1]
    try:
        {"generate": generate, "publish": publish, "command": command, "refresh": refresh,
         "rerender": rerender}[action]()
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            raise
        import traceback
        tb = traceback.format_exc()[-2500:]
        try:
            comment(control_issue(), f"⚠️ 봇 `{action}` 실행 중 오류\n\n```\n{tb}\n```")
        except Exception:
            pass
        raise
