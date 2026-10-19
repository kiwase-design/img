"""회차 렌더링: 컷 그림 생성(Gemini) → 말풍선·대사 합성(Pillow).

사용법:
  python scripts/render_episode.py episodes/ep001            # 없는 컷만 그림 생성 + 전체 합성
  python scripts/render_episode.py episodes/ep001 --force    # 모든 컷 다시 그림
  python scripts/render_episode.py episodes/ep001 --compose  # 합성만 (raw 그림 재사용)

산출물:
  <ep>/raw/cutN.png    AI가 그린 원본 컷
  <ep>/final/NN.png    인스타 업로드용 1080x1350 완성본
  <ep>/report.md       실행 결과 요약
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

from PIL import Image, ImageDraw, ImageFont

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image"]
W, H = 1080, 1350
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_INDEX = 1  # NotoSansCJK .ttc 안의 KR 폰트
HAND_FONT = "fonts/hand.ttf"  # 시리즈 손글씨 폰트 (있으면 우선 사용)

SERIES = json.load(open("config/series.json", encoding="utf-8"))
CHARS = SERIES["characters"]

STYLE = (
    "One single panel of a Korean Instagram webtoon (instatoon). "
    f"Art style: {SERIES['style']} "
    "Draw the characters EXACTLY as shown in the attached character reference sheets "
    "(same face, body shape, hair, proportions, same drawing style). "
    "IMPORTANT: keep the top 28% of the image as calm, plain, empty paper "
    "(no characters, no objects) because speech bubbles will be added there later. "
    "One full-bleed scene: no panel border, no frame lines, no inner panels. "
    "Absolutely no text, no letters, no speech bubbles, no captions, no watermark, "
    "and no real brand names, logos, trademarks, mascots or famous characters on any object. "
    "Any signboards or billboards must be blank colored shapes."
)


def font(size):
    if os.path.exists(HAND_FONT):
        return ImageFont.truetype(HAND_FONT, int(size * 1.3))  # 손글씨체는 작게 보여서 키움
    return ImageFont.truetype(FONT_PATH, size, index=FONT_INDEX)


# ---------- 1. 그림 생성 ----------

def _inline_png(path):
    mime = "image/jpeg" if path.endswith((".jpg", ".jpeg")) else "image/png"
    with open(path, "rb") as f:
        return {"inlineData": {"mimeType": mime, "data": base64.b64encode(f.read()).decode()}}


def generate_panel(key, panel):
    parts = []
    refs = []
    for i, c in enumerate(panel["characters"], start=1):
        parts.append(_inline_png(CHARS[c]["ref"]))
        refs.append(f"Reference image {len(parts)} = {CHARS[c]['desc']}")
        base = CHARS[c].get("base_ref")
        if base and os.path.exists(base):
            parts.append(_inline_png(base))
            refs.append(f"Reference image {len(parts)} = the ORIGINAL hand drawing of {CHARS[c]['name']}; "
                        "match its asymmetric swooping hair curl with loop, separate oval head on the body, and stubble dots.")
    prompt = f"{STYLE}\n\n{' '.join(refs)}\n\nScene: {panel['scene']}"
    parts.append({"text": prompt})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "4:5"}},
    }
    errors = []
    for model in MODELS:
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
            errors.append(f"{model}: HTTP {e.code} {msg}")
            continue
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"]), model, None
        errors.append(f"{model}: 이미지 없음")
    return None, None, " / ".join(errors)


# ---------- 2. 말풍선 합성 ----------

def fit_cover(img):
    """4:5 비율로 중앙 크롭 후 1080x1350 으로 리사이즈."""
    img = img.convert("RGB")
    target = W / H
    w, h = img.size
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize((W, H), Image.LANCZOS)


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:  # 단어가 너무 길면 글자 단위로 자름
            if draw.textlength(cur + ch, font=font) > max_w and cur:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
    if cur:
        lines.append(cur)
    return lines


def draw_bubble(draw, text, side, top, font):
    pad_x, pad_y, line_gap, outline = 44, 30, 12, 5
    max_text_w = 720
    lines = wrap(draw, text, font, max_text_w)
    asc, desc = font.getmetrics()
    lh = asc + desc
    tw = max(draw.textlength(l, font=font) for l in lines)
    bw = int(tw + pad_x * 2)
    bh = int(len(lines) * lh + (len(lines) - 1) * line_gap + pad_y * 2)

    margin = 60
    if side == "left":
        x0 = margin
    elif side == "right":
        x0 = W - margin - bw
    else:
        x0 = (W - bw) // 2
    x1, y0, y1 = x0 + bw, top, top + bh
    r = min(60, bh // 2)

    # 꼬리 (말하는 캐릭터 쪽 아래로)
    tail_len = 46
    if side == "left":
        base_cx, tip = x0 + bw * 0.28, (x0 + bw * 0.18, y1 + tail_len)
    elif side == "right":
        base_cx, tip = x0 + bw * 0.72, (x0 + bw * 0.82, y1 + tail_len)
    else:
        base_cx, tip = x0 + bw * 0.5, (x0 + bw * 0.5, y1 + tail_len)
    tail = [(base_cx - 26, y1 - 8), (base_cx + 26, y1 - 8), tip]

    # 외곽선 → 흰 채움 순서로 그려 꼬리와 몸통이 자연스럽게 이어지게
    draw.rounded_rectangle((x0 - outline, y0 - outline, x1 + outline, y1 + outline), r + outline, fill="black")
    draw.polygon([(tail[0][0] - outline * 1.6, tail[0][1]), (tail[1][0] + outline * 1.6, tail[1][1]),
                  (tip[0], tip[1] + outline * 1.8)], fill="black")
    draw.rounded_rectangle((x0, y0, x1, y1), r, fill="white")
    draw.polygon(tail, fill="white")

    y = y0 + pad_y
    for l in lines:
        lw = draw.textlength(l, font=font)
        draw.text((x0 + (bw - lw) / 2, y), l, font=font, fill="black")
        y += lh + line_gap
    return y1 + tail_len


def compose(raw_path, panel, out_path, ep_title, ep_no):
    img = fit_cover(Image.open(raw_path))
    draw = ImageDraw.Draw(img)
    fnt = font(48)
    top = 70
    merged = []  # 같은 인물이 연달아 말하면 말풍선 하나로
    for dl in panel["dialogues"]:
        if merged and merged[-1]["speaker"] == dl["speaker"]:
            merged[-1] = {**merged[-1], "text": merged[-1]["text"] + " " + dl["text"]}
        else:
            merged.append(dict(dl))
    for dl in merged:
        bottom = draw_bubble(draw, dl["text"], dl.get("side", "center"), top, fnt)
        top = bottom + 14

    # 하단 작은 표기 (회차/컷)
    small = font(26)
    label = f"{SERIES['short_title']} {ep_no}화 · {panel['cut']}/{SERIES['panels']}"
    lw = draw.textlength(label, font=small)
    draw.rounded_rectangle((W - lw - 56, H - 62, W - 20, H - 18), 18, fill=(255, 255, 255))
    draw.text((W - lw - 38, H - 58), label, font=small, fill=(90, 90, 90))
    img.save(out_path, optimize=True)


# ---------- main ----------

def main():
    ep_dir = sys.argv[1].rstrip("/")
    compose_only = "--compose" in sys.argv
    force = "--force" in sys.argv  # 기존 raw 그림이 있어도 다시 그림
    script = json.load(open(f"{ep_dir}/script.json", encoding="utf-8"))
    os.makedirs(f"{ep_dir}/raw", exist_ok=True)
    os.makedirs(f"{ep_dir}/final", exist_ok=True)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    report = [f"# {script['episode']}화 「{script['title']}」 렌더링 결과", "", f"- 실행 시각: {kst}"]

    for panel in script["panels"]:
        n = panel["cut"]
        raw = f"{ep_dir}/raw/cut{n}.png"
        if not compose_only and (force or not os.path.exists(raw)):
            if not key:
                report.append("- ❌ GEMINI_API_KEY 없음")
                break
            img, model, err = generate_panel(key, panel)
            if not img:
                report.append(f"- 컷{n}: ❌ {err}")
                continue
            with open(raw, "wb") as f:
                f.write(img)
            report.append(f"- 컷{n}: ✅ 그림 생성 ({model})")
        if os.path.exists(raw):
            compose(raw, panel, f"{ep_dir}/final/{n:02d}.png", script["title"], script["episode"])
            report.append(f"- 컷{n}: ✅ 합성 → `final/{n:02d}.png`")

    with open(f"{ep_dir}/report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
