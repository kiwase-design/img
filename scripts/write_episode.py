"""다음 회차 대본(script.json)을 Gemini로 작성 (config/series.json 기반).

사용법: python scripts/write_episode.py episodes/ep002 [도시]

1) 여행지 정하기: 인자로 받은 도시 → config/next_city.txt → 지난 회차와 겹치지 않게 AI가 선택
2) 구글 검색 근거(grounding)로 그 도시의 최신 여행 정보 조사
3) 조사 내용 + 시리즈 바이블로 대본 작성
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
CHARS = SERIES["characters"]
N = SERIES["panels"]
SIDES = {"left", "right", "center"}


def call(key, model, prompt, json_out=False, search=False):
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.9}}
    if json_out:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if search:
        body["tools"] = [{"google_search": {}}]
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent", method="POST",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        data = json.loads(r.read())
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


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
            found.append((float(mt.group(1)), mt.group(2) == "pro", name))
    found.sort(reverse=True)
    return [n for _, _, n in found]


def past_episodes(ep_dir):
    out = []
    for p in sorted(glob.glob("episodes/ep*/script.json")):
        if os.path.dirname(p) == ep_dir:
            continue
        s = json.load(open(p, encoding="utf-8"))
        out.append(f"- {s['episode']}화 「{s['title']}」 ({s.get('city', '?')})")
    return "\n".join(out[-30:]) or "(아직 없음)"


def choose_city(ep_dir):
    if len(sys.argv) > 2 and sys.argv[2].strip():
        return sys.argv[2].strip()
    if os.path.exists("config/next_city.txt"):
        c = open("config/next_city.txt", encoding="utf-8").read().strip()
        if c:
            return c
    return None


def validate(s):
    assert isinstance(s.get("title"), str) and s["title"]
    assert isinstance(s.get("caption"), str) and "#" in s["caption"]
    assert len(s["panels"]) == N
    for i, p in enumerate(s["panels"], 1):
        p["cut"] = i
        assert p["characters"] and set(p["characters"]) <= set(CHARS)
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
    models = pick_models(key)
    city = choose_city(ep_dir)
    history = past_episodes(ep_dir)

    # 1) 여행지 선택
    if not city:
        city = call(key, models[0],
                    "한국인 여행자에게 인기 있는 해외(또는 국내) 여행 도시 하나만 골라 도시 이름만 한 줄로 답하세요. "
                    f"다음 회차와 겹치면 안 됩니다:\n{history}").strip().splitlines()[0][:30]

    # 2) 최신 여행 정보 조사 (구글 검색 근거, 실패하면 일반 지식)
    ask = (f"{city} 여행 정보를 한국인 가족 여행자 관점에서 정리해줘. 항목: 도시 한 줄 소개, 대표 볼거리 2곳, "
           "대표 먹거리 2개, 기타 구경거리(시장·골목·체험) 1~2개, 솔직한 단점 2개(물가·날씨·인파·교통 등), "
           "여행 팁 1개. 확실한 사실만, 정확한 가격·운영시간처럼 자주 바뀌는 숫자는 쓰지 말 것. 짧게 불릿으로.")
    research, grounded = "", False
    for m in models:
        try:
            research, grounded = call(key, m, ask, search=True), True
            break
        except urllib.error.HTTPError:
            continue
    if not research:
        research = call(key, models[0], ask)

    # 3) 대본 작성
    cast = "\n".join(f"- {cid}: {c['name']} — {c['role']}" for cid, c in CHARS.items())
    structure = "\n".join(f"{i}컷: {t}" for i, t in enumerate(SERIES["structure"], 1))
    tags = " ".join(SERIES["hashtags"])
    main_id = next(iter(CHARS))
    prompt = f"""당신은 인기 여행 인스타툰 작가입니다. 아래 시리즈 바이블에 맞춰 {ep_no}화 대본을 쓰세요.
이번 여행지: {city}

# 시리즈 바이블
{bible}

# 등장인물 id
{cast}

# 여행지 조사 자료 (이 사실만 사용)
{research}

# 지난 회차
{history}

# 컷 구성 (정확히 {N}컷)
{structure}

# 규칙
- 정보가 핵심: 각 컷 대사에 실제 장소·음식 이름 등 구체적인 정보를 담을 것. 조사 자료에 없는 사실은 지어내지 말 것.
- 컷당 대사 0~2개, 대사 하나는 28자 이내. {CHARS[main_id]['name']}는 부산 사투리 (예: ~아이가, ~한다 아이가, 마, 억수로, ~캐라).
- 가족 캐릭터 성격을 살려 짧은 웃음 포인트를 넣을 것 (흑곰은 늘 먹음, 바다표범은 느리고 눈치 없음, 오목눈이는 말 많고 성깔 있음).
- 마지막 컷은 {CHARS[main_id]['name']}가 독자를 향해 요약 + 좋아요/저장 강요.
- characters 는 그 컷에 그려질 캐릭터 id. side 는 말하는 캐릭터의 그림 속 위치, scene 의 좌우 배치와 일치시킬 것.
- scene 은 영어로, 그 장소를 알 수 있는 랜드마크 형태·음식 모양을 간단히 묘사. 그림 속 글자·간판·로고는 금지.
- 정치·종교·실존 인물·폭력·선정적 내용 금지.

# 출력 (JSON 하나만)
{{
  "title": "회차 제목 (도시 이름 포함, 15자 이내)",
  "caption": "인스타 캡션: 첫 줄 '{SERIES['title']} {ep_no}화 ✈️ {city}', 빈 줄, 핵심 정보 요약 3~5줄(이모지 불릿), 빈 줄, '저장해두고 여행 갈 때 꺼내보이소!' 같은 한 줄, 빈 줄, 해시태그 ({tags} + 도시 관련 3~4개)",
  "panels": [
    {{"cut": 1, "characters": ["{main_id}", ...], "scene": "English visual description",
      "dialogues": [{{"speaker": "{main_id}", "text": "대사", "side": "left|right|center"}}]}}
  ]
}}"""

    errors = []
    for model in models:
        for _ in range(2):
            try:
                script = json.loads(call(key, model, prompt, json_out=True))
                validate(script)
            except urllib.error.HTTPError as e:
                errors.append(f"{model}: HTTP {e.code}")
                break
            except Exception as e:
                errors.append(f"{model}: 형식 오류 {type(e).__name__}")
                continue
            out = {"episode": ep_no, "city": city, "title": script["title"], "caption": script["caption"],
                   "panels": script["panels"], "writer_model": model, "grounded_research": grounded,
                   "research": research}
            os.makedirs(ep_dir, exist_ok=True)
            with open(f"{ep_dir}/script.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
                f.write("\n")
            if os.path.exists("config/next_city.txt"):
                os.remove("config/next_city.txt")
            print(f"✅ {ep_no}화 「{out['title']}」 대본 작성 ({model}, 검색근거={grounded})")
            return
    raise SystemExit("대본 작성 실패: " + " / ".join(errors))


if __name__ == "__main__":
    main()
