"""다음 편 여행영어 대본(script.json)을 Gemini로 작성.

사용법: python scripts/write_episode.py episodes/ep002 [상황]

상황 고르기: 인자 → config/next_topic.txt → config/situations.json 에서 아직 안 다룬 첫 상황
"""
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://generativelanguage.googleapis.com/v1beta"
SERIES = json.load(open("config/series.json", encoding="utf-8"))
HERO_ID = next(iter(SERIES["characters"]))
HERO = SERIES["characters"][HERO_ID]


def call(key, model, prompt):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"}}
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent", method="POST",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        data = json.loads(r.read())
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])


def pick_models(key):
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
            found.append((mt.group(2) == "pro", float(mt.group(1)), name))  # 정확도가 중요해서 pro 우선
    found.sort(reverse=True)
    return [n for _, _, n in found]


def done_topics(ep_dir):
    out = []
    for p in sorted(glob.glob("episodes/ep*/script.json")):
        if os.path.dirname(p) != ep_dir:
            out.append(json.load(open(p, encoding="utf-8")).get("topic", ""))
    return out


def choose_topic(ep_dir):
    if len(sys.argv) > 2 and sys.argv[2].strip():
        return sys.argv[2].strip()
    if os.path.exists("config/next_topic.txt"):
        t = open("config/next_topic.txt", encoding="utf-8").read().strip()
        if t:
            return t
    done = set(done_topics(ep_dir))
    for t in json.load(open("config/situations.json", encoding="utf-8")):
        if t not in done:
            return t
    raise SystemExit("상황 목록을 모두 다뤘어요. config/situations.json 에 상황을 추가하세요.")


def validate(s):
    for k in ("title", "headline", "sub", "cover_scene", "summary_scene", "tip", "caption"):
        assert isinstance(s.get(k), str) and s[k].strip(), k
    assert len(s["panels"]) == 4
    for p in s["panels"]:
        assert isinstance(p["scene"], str) and len(p["scene"]) > 30
        assert len(p["dialogues"]) == 2
        for d in p["dialogues"]:
            assert d["speaker"] in ("staff", HERO_ID)
            assert d["en"].strip() and d["ko"].strip()
            assert len(d["en"].split()) <= 16
    assert 3 <= len(s["key_phrases"]) <= 5
    for k in s["key_phrases"]:
        assert k["en"].strip() and k["ko"].strip()


def main():
    ep_dir = sys.argv[1].rstrip("/")
    ep_no = int(re.search(r"ep(\d+)", ep_dir).group(1))
    key = os.environ["GEMINI_API_KEY"].strip()
    topic = choose_topic(ep_dir)
    tags = " ".join(SERIES["hashtags"])

    prompt = f"""You are an experienced English teacher who writes viral Instagram carousels teaching Korean travelers practical English.
Topic (situation): {topic}
Main character: {HERO['name']} ({HERO_ID}), a Korean traveler in her early 20s. The other person is local staff or a local ("staff").

Write ONE short realistic conversation for this situation as 4 exchanges. Each exchange = 2 lines (usually staff then {HERO_ID}, or the reverse when she starts).
Rules for the English:
- Natural, polite English that native speakers really use at that place today. Not textbook-stiff, not slang.
- Each line max 14 words. Easy (A2–B1), but useful. Include the 3–5 most useful phrases a traveler needs here.
- The conversation must flow logically from start to finish of the situation.
- No brand names, airline names, real people, politics or religion.
Korean ("ko"): natural Korean translation a Korean would actually say, not word-for-word (avoid stiff words like '완벽합니다').
key_phrases: 3–5 items, mostly lines the TRAVELER says (ready to copy), plus at most one staff question she must understand.

Images: every exchange gets one photo. Write "scene" in English as a photo description: location, who is where, actions, expressions.
{HERO['name']} is always in the photo. Staff appearance should fit the place (mixed ethnicities). No readable text, signs, screens, logos or uniforms with brands.

Return JSON only:
{{
  "title": "Korean post title, max 14 chars (e.g. 공항 체크인 영어)",
  "other_label": "Korean label for the other person, 2–3 chars: 직원 / 현지인 / 기사님 / 의사 / 약사 etc.",
  "headline": "Korean cover headline, max 10 chars (e.g. 공항 체크인)",
  "sub": "Korean cover subline, max 16 chars, catchy (e.g. 이 네 마디면 끝!)",
  "cover_scene": "English photo description for the cover: {HERO['name']} at this place, looking at the camera with a friendly smile",
  "panels": [
    {{"scene": "English photo description",
      "dialogues": [{{"speaker": "staff", "en": "...", "ko": "..."}}, {{"speaker": "{HERO_ID}", "en": "...", "ko": "..."}}]}}
  ],
  "key_phrases": [{{"en": "most useful phrase", "ko": "해석"}}],
  "tip": "One practical Korean tip for this situation, max 40 chars",
  "summary_scene": "English photo description for the last slide: {HERO['name']} happy after finishing the situation",
  "caption": "Korean Instagram caption: line 1 '{SERIES['title']} #{ep_no} | <title>', blank line, 2 lines hook, blank line, the key phrases as '✔️ English — 한국어' lines, blank line, '저장해두고 여행 갈 때 꺼내 보세요! 💾', blank line, '{SERIES['ai_notice']}', blank line, hashtags: {tags} plus 3 topic hashtags"
}}"""

    errors = []
    for model in pick_models(key):
        for _ in range(2):
            try:
                s = json.loads(call(key, model, prompt))
                validate(s)
            except urllib.error.HTTPError as e:
                errors.append(f"{model}: HTTP {e.code}")
                break
            except Exception as e:
                errors.append(f"{model}: 형식 오류 {type(e).__name__} {e}")
                continue
            for i, p in enumerate(s["panels"], 2):
                p["cut"] = i
                p["characters"] = [HERO_ID]
            out = {"episode": ep_no, "topic": topic, **s, "writer_model": model}
            os.makedirs(ep_dir, exist_ok=True)
            with open(f"{ep_dir}/script.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
                f.write("\n")
            if os.path.exists("config/next_topic.txt"):
                os.remove("config/next_topic.txt")
            print(f"✅ #{ep_no} 「{s['title']}」 ({topic}) 대본 작성 ({model})")
            return
    raise SystemExit("대본 작성 실패: " + " / ".join(errors))


if __name__ == "__main__":
    main()
