"""캐릭터 기준 설정화 생성 (config/series.json 기반).

- 설정화가 아직 없는 캐릭터만 그린다. 다시 그리려면 해당 png를 지우고 실행.
- 주인공의 원본 스케치(base_ref)를 모든 캐릭터의 화풍 기준으로 함께 넣는다.
결과 요약은 checks/character_gen.md 에 기록.
"""
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image"]
REPORT = "checks/character_gen.md"
SERIES = json.load(open("config/series.json", encoding="utf-8"))

SHEET = (
    "Character design sheet for a Korean Instagram webtoon. "
    "Show the SAME character three times side by side: front view, three-quarter view, side view, "
    "full body, standing, neutral pose, on plain white paper. No text, no labels, no logos."
)


SHEET = SERIES.get("sheet_prompt", SHEET)


def inline(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return {"inlineData": {"mimeType": mime, "data": base64.b64encode(f.read()).decode()}}


def generate(key, model, parts):
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}},
    }
    req = urllib.request.Request(
        f"{BASE}/models/{model}:generateContent", method="POST",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        data=json.dumps(body).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")[:200]
        except Exception:
            msg = ""
        return None, f"HTTP {e.code} — {msg}"
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inl = part.get("inlineData") or part.get("inline_data")
            if inl and inl.get("data"):
                return base64.b64decode(inl["data"]), None
    return None, "응답에 이미지 없음"


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    lines = ["# 캐릭터 설정화 생성 결과", "", f"- 실행 시각: {kst}"]
    chars = SERIES["characters"]
    main_id = next(iter(chars))
    base_ref = chars[main_id].get("base_ref")

    for cid, c in chars.items():
        if os.path.exists(c["ref"]):
            lines.append(f"- {c['name']}: 이미 있음 (건너뜀)")
            continue
        parts, notes = [], []
        if base_ref and os.path.exists(base_ref):
            parts.append(inline(base_ref))
            notes.append("Image 1 is the original hand-drawn sketch of the main character "
                         f"{chars[main_id]['name']}. Copy its drawing style exactly (line quality, simplicity, proportions).")
        main_sheet = chars[main_id]["ref"]
        if cid != main_id and os.path.exists(main_sheet):
            parts.append(inline(main_sheet))
            notes.append(f"Image {len(parts)} is the finished design sheet of the main character; "
                         "the new character must look like they belong in the same family / same comic.")
        prompt = f"{' '.join(notes)}\n\n{SHEET}\n\nArt style: {SERIES['style']}\n\nCharacter: {c['desc']}"
        if cid == main_id:
            prompt += "\n\nThis character must look exactly like the sketch in image 1 — same face, hair loop, body shape."
        parts.append({"text": prompt})

        errors = []
        for model in MODELS:
            img, err = generate(key, model, parts)
            if img:
                os.makedirs(os.path.dirname(c["ref"]), exist_ok=True)
                with open(c["ref"], "wb") as f:
                    f.write(img)
                lines.append(f"- {c['name']}: ✅ `{c['ref']}` ({model})")
                break
            errors.append(f"{model}: {err}")
        else:
            lines.append(f"- {c['name']}: ❌ " + " / ".join(errors))

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
