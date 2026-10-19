"""캐릭터 기준 설정화 생성.

series_bible.md 의 설정을 바탕으로 주인공·조연 설정화를 그려
characters/ 폴더에 저장한다. 결과 요약은 checks/character_gen.md 에 기록.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image"]  # 앞에서부터 시도
OUT_DIR = "characters"
REPORT = "checks/character_gen.md"

STYLE = (
    "Korean Instagram webtoon (instatoon) character design sheet. "
    "Simple flat 2D illustration, bold clean black outlines, soft pastel colors, "
    "cute round chibi-like proportions, plain pure white background, no text, no logos, "
    "no watermark. Show the SAME character three times side by side: "
    "front view, three-quarter view, and side view, full body, standing, neutral pose."
)

CHARACTERS = {
    "nyang_daeri": (
        "Main character 'Nyang Daeri': an anthropomorphic young office-worker cat. "
        "Gray tabby fur with darker gray stripes, big round bright green eyes, "
        "white muzzle and chest, wearing a white short-sleeve dress shirt and a navy blue necktie, "
        "gray slacks. Personality: lazy but sharp, sly half-lidded smile."
    ),
    "meong_bujang": (
        "Supporting character 'Meong Bujang': an anthropomorphic golden retriever office manager. "
        "Fluffy golden fur, floppy ears, big cheerful open-mouth smile, slightly taller and bigger "
        "than a cat, wearing a light blue dress shirt with rolled sleeves and a red necktie, "
        "brown slacks. Personality: overly enthusiastic boss, always smiling."
    ),
    "ham_jumin": (
        "Supporting character 'Ham Jumin': an anthropomorphic hamster office worker, small and round. "
        "Orange-cream and white fur, chubby cheeks, small black eyes, round glasses, "
        "wearing a beige cardigan over a white shirt, holding a tiny notebook. "
        "Personality: timid and worried, slightly nervous expression."
    ),
}


def generate(key, model, prompt):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "16:9"},
        },
    }
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent",
        method="POST",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        return None, f"HTTP {e.code} — {msg}"

    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), None
    reason = (data.get("candidates") or [{}])[0].get("finishReason", "이미지 없음")
    return None, f"응답에 이미지 없음 ({reason})"


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    lines = ["# 캐릭터 설정화 생성 결과", "", f"- 실행 시각: {kst}"]
    os.makedirs(OUT_DIR, exist_ok=True)

    if not key:
        lines.append("- ❌ `GEMINI_API_KEY` 시크릿 없음")
        return write(lines)

    for name, desc in CHARACTERS.items():
        prompt = f"{STYLE}\n\nCharacter: {desc}"
        errors = []
        for model in MODELS:
            img, err = generate(key, model, prompt)
            if img:
                path = f"{OUT_DIR}/{name}.png"
                with open(path, "wb") as f:
                    f.write(img)
                lines.append(f"- {name}: ✅ `{path}` ({model}, {len(img)//1024}KB)")
                break
            errors.append(f"{model}: {err}")
        else:
            lines.append(f"- {name}: ❌ " + " / ".join(errors))

    write(lines)


def write(lines):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
