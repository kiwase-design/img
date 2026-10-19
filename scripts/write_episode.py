"""다음 회차 대본(script.json)을 Gemini로 작성.

사용법: python scripts/write_episode.py episodes/ep002

- series_bible.md 와 지난 회차들의 대사를 참고해 겹치지 않는 새 에피소드를 쓴다.
- 사용 가능한 최신 Gemini 텍스트 모델을 자동으로 골라 쓴다.
"""
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
CHARS = {"nyang_daeri", "meong_bujang", "ham_jumin"}
SIDES = {"left", "right", "center"}

SCHEMA_HINT = """{
  "title": "회차 제목 (한국어, 10자 이내)",
  "caption": "인스타 캡션 (한국어). 첫 줄 '오늘도 출근한 고양이 N화 🐱 제목', 빈 줄, 공감 한두 문장, 빈 줄, 해시태그 6~9개 (#오늘도출근한고양이 #냥대리 #인스타툰 #직장인공감 포함)",
  "panels": [
    {
      "cut": 1,
      "characters": ["nyang_daeri", ...],   // 이 컷에 그려질 캐릭터 id
      "scene": "ENGLISH visual description for the illustrator: setting, who is where (left/right), poses, facial expressions, effects",
      "dialogues": [
        {"speaker": "nyang_daeri", "text": "한국어 대사", "side": "left|right|center"}
      ]
    }
  ]
}"""

RULES = """규칙:
- 정확히 4컷. 구조: 상황 제시 → 전개 → 반전 → 웃음 포인트.
- 직장인이 공감할 만한 구체적인 회사 일상 소재 하나. 지난 회차와 소재·펀치라인이 겹치지 않게.
- 캐릭터 id는 nyang_daeri(냥대리), meong_bujang(멍부장), ham_jumin(햄주임) 만 사용. 모든 컷에 냥대리가 나오는 게 좋음.
- 컷당 대사 0~2개, 대사 하나는 25자 이내로 짧게. 냥대리 대사는 '…냥/다냥' 말버릇을 자연스럽게.
- side 는 말하는 캐릭터가 그림에서 서 있는 쪽. scene 설명의 좌우 배치와 반드시 일치시킬 것.
- scene 은 영어로, 그림에 글자·간판·상표·로고가 들어가지 않게 (요일·숫자 정도만 허용).
- 정치·종교·실존 인물·실제 브랜드·폭력·선정적 내용 금지.
- JSON 하나만 출력."""


def call(key, model, prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent", method="POST",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def pick_models(key):
    """generateContent 를 지원하는 정식(stable) gemini-X-pro/flash 모델을 최신순으로."""
    req = urllib.request.Request(f"{BASE}/models?pageSize=1000", headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        models = json.loads(r.read()).get("models", [])
    found = []
    for m in models:
        name = m["name"].removeprefix("models/")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        mt = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-(pro|flash)", name)
        if mt:
            found.append((float(mt.group(1)), mt.group(2) == "pro", name))
    found.sort(reverse=True)
    return [n for _, _, n in found]


def past_summaries(ep_dir):
    out = []
    for p in sorted(glob.glob("episodes/ep*/script.json")):
        if os.path.dirname(p) == ep_dir:
            continue
        s = json.load(open(p, encoding="utf-8"))
        lines = " / ".join(d["text"] for pan in s["panels"] for d in pan["dialogues"])
        out.append(f"- {s['episode']}화 「{s['title']}」: {lines}")
    return "\n".join(out[-15:]) or "(아직 없음)"


def validate(s):
    assert isinstance(s.get("title"), str) and s["title"]
    assert isinstance(s.get("caption"), str) and "#" in s["caption"]
    assert len(s["panels"]) == 4
    for i, p in enumerate(s["panels"], 1):
        p["cut"] = i
        assert p["characters"] and set(p["characters"]) <= CHARS
        assert isinstance(p["scene"], str) and len(p["scene"]) > 20
        assert len(p["dialogues"]) <= 2
        for d in p["dialogues"]:
            assert d["speaker"] in CHARS and d["text"].strip()
            if d.get("side") not in SIDES:
                d["side"] = "center"


def main():
    ep_dir = sys.argv[1].rstrip("/")
    ep_no = int(re.search(r"ep(\d+)", ep_dir).group(1))
    key = os.environ["GEMINI_API_KEY"].strip()
    bible = open("series_bible.md", encoding="utf-8").read()

    prompt = (
        f"당신은 인기 인스타툰 작가입니다. 아래 시리즈 바이블에 맞춰 {ep_no}화 대본을 쓰세요.\n\n"
        f"# 시리즈 바이블\n{bible}\n\n# 지난 회차 (겹치지 않게)\n{past_summaries(ep_dir)}\n\n"
        f"{RULES}\n\n# 출력 형식\n{SCHEMA_HINT}"
    )

    errors = []
    for model in pick_models(key):
        for attempt in range(2):
            try:
                script = json.loads(call(key, model, prompt))
                validate(script)
            except urllib.error.HTTPError as e:
                errors.append(f"{model}: HTTP {e.code}")
                break  # 이 모델은 못 씀 → 다음 모델
            except Exception as e:
                errors.append(f"{model}: 형식 오류 {type(e).__name__}")
                continue
            out = {"episode": ep_no, "title": script["title"], "caption": script["caption"],
                   "panels": script["panels"], "writer_model": model}
            os.makedirs(ep_dir, exist_ok=True)
            with open(f"{ep_dir}/script.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"✅ {ep_no}화 「{out['title']}」 대본 작성 ({model})")
            return
    raise SystemExit("대본 작성 실패: " + " / ".join(errors))


if __name__ == "__main__":
    main()
