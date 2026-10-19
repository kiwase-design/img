"""여행영어 한 편 렌더링: 실사 사진 생성(Gemini) → 자막 카드 합성(Pillow).

사용법:
  python scripts/render_episode.py episodes/ep001            # 없는 사진만 생성 + 전체 합성
  python scripts/render_episode.py episodes/ep001 --force    # 모든 사진 다시 생성
  python scripts/render_episode.py episodes/ep001 --compose  # 합성만

산출물:
  <ep>/raw/cutN.png   생성된 원본 사진 (1=표지, 2~5=대화, 6=정리)
  <ep>/final/NN.png   인스타 업로드용 1080x1350
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3-pro-image", "gemini-3.1-flash-image"]
W, H = 1080, 1350
NOTO = "/usr/share/fonts/opentype/noto/NotoSansCJK-{}.ttc"
SERIES = json.load(open("config/series.json", encoding="utf-8"))
HERO_ID = next(iter(SERIES["characters"]))
HERO = SERIES["characters"][HERO_ID]

ACCENT = (255, 94, 98)      # 주인공 라벨 (코랄)
STAFF = (70, 110, 160)      # 상대방 라벨 (블루)
INK = (25, 25, 30)
SUB = (95, 95, 105)

PHOTO_RULES = (
    f"{SERIES['style']} "
    f"The young woman in the photo is {HERO['name']}: she must look EXACTLY like the woman in the reference image "
    "(same face, same hair, same outfit). She is a fictional person. "
    "Absolutely no readable text, letters, numbers, signs, screens with text, logos, airline or brand names anywhere. "
    "No watermark, no captions, no speech bubbles."
)
BOTTOM_SAFE = " Compose so faces and key action are in the upper 60% of the frame; the lower part may be counters, floor or soft blur."


def font(weight, size):
    return ImageFont.truetype(NOTO.format(weight), size, index=1)


# ---------- 사진 생성 ----------

def generate_photo(key, scene, bottom_safe=True):
    with open(HERO["ref"], "rb") as f:
        ref = {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(f.read()).decode()}}
    prompt = f"{PHOTO_RULES}{BOTTOM_SAFE if bottom_safe else ''}\n\nScene: {scene}"
    body = {
        "contents": [{"parts": [ref, {"text": prompt}]}],
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
            errors.append(f"{model}: HTTP {e.code}")
            continue
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inl = part.get("inlineData") or part.get("inline_data")
                if inl and inl.get("data"):
                    return base64.b64decode(inl["data"]), model, None
        errors.append(f"{model}: 이미지 없음")
    return None, None, " / ".join(errors)


# ---------- 합성 도구 ----------

def fit_cover(img):
    img = img.convert("RGB")
    t = W / H
    w, h = img.size
    if w / h > t:
        nw = int(h * t)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / t)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize((W, H), Image.LANCZOS)


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def text_block(draw, x, y, text, fnt, fill, max_w, gap=8, measure=False):
    lines = wrap(draw, text, fnt, max_w)
    asc, desc = fnt.getmetrics()
    for ln in lines:
        if not measure:
            draw.text((x, y), ln, font=fnt, fill=fill)
        y += asc + desc + gap
    return y


def badge(draw, x, y, text, color, fnt):
    tw = draw.textlength(text, font=fnt)
    asc, desc = fnt.getmetrics()
    draw.rounded_rectangle((x, y, x + tw + 32, y + asc + desc + 14), 22, fill=color)
    draw.text((x + 16, y + 6), text, font=fnt, fill="white")
    return x + tw + 32


def overlay(img, box, fill, radius=36):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=fill)
    return Image.alpha_composite(img.convert("RGBA"), layer)


def footer(draw, ep_no, n, total):
    f = font("Medium", 24)
    label = f"{SERIES['short_title']} #{ep_no}   {n}/{total}"
    tw = draw.textlength(label, font=f)
    draw.text((W - tw - 44, 40), label, font=f, fill=(255, 255, 255, 230),
              stroke_width=2, stroke_fill=(0, 0, 0, 90))


# ---------- 슬라이드 ----------

def compose_cover(raw, s, out, total):
    img = fit_cover(Image.open(raw)).convert("RGBA")
    grad = Image.new("L", (1, H))
    for yy in range(H):  # 아래쪽을 어둡게
        grad.putpixel((0, yy), int(max(0, (yy - H * 0.45) / (H * 0.55)) * 210))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    shade.putalpha(grad.resize((W, H)))
    img = Image.alpha_composite(img, shade)
    d = ImageDraw.Draw(img)
    footer(d, s["episode"], 1, total)
    y = H - 430
    badge(d, 64, y, "여행 필수 영어", ACCENT, font("Bold", 30))
    y += 74
    y = text_block(d, 64, y, s["headline"], font("Black", 104), "white", W - 128, gap=4)
    text_block(d, 64, y + 6, s["sub"], font("Bold", 46), (255, 230, 225), W - 128)
    img.convert("RGB").save(out, optimize=True)


def compose_dialogue(raw, s, panel, out, total):
    img = fit_cover(Image.open(raw)).convert("RGBA")
    d = ImageDraw.Draw(img)
    f_en, f_ko, f_lb = font("Bold", 44), font("Regular", 32), font("Bold", 26)
    pad, mx = 44, 40
    max_w = W - 2 * mx - 2 * pad
    # 카드 높이 계산
    h = pad
    for dl in panel["dialogues"]:
        h += 54
        h = text_block(d, 0, h, dl["en"], f_en, INK, max_w, measure=True)
        h = text_block(d, 0, h + 2, dl["ko"], f_ko, SUB, max_w, measure=True) + 22
    h += pad - 22
    top = H - 48 - h
    img = overlay(img, (mx, top, W - mx, H - 48), (255, 255, 255, 238))
    d = ImageDraw.Draw(img)
    footer(d, s["episode"], panel["cut"], total)
    y = top + pad
    for i, dl in enumerate(panel["dialogues"]):
        hero = dl["speaker"] == HERO_ID
        badge(d, mx + pad, y, HERO["name"] if hero else "현지인", ACCENT if hero else STAFF, f_lb)
        y += 54
        y = text_block(d, mx + pad, y, dl["en"], f_en, INK, max_w)
        y = text_block(d, mx + pad, y + 2, dl["ko"], f_ko, SUB, max_w) + 22
        if i == 0:
            d.line((mx + pad, y - 12, W - mx - pad, y - 12), fill=(225, 225, 230), width=2)
    img.convert("RGB").save(out, optimize=True)


def compose_summary(raw, s, out, total):
    img = fit_cover(Image.open(raw)).filter(ImageFilter.GaussianBlur(3)).convert("RGBA")
    img = Image.alpha_composite(img, Image.new("RGBA", (W, H), (0, 0, 0, 70)))
    mx, pad = 56, 52
    max_w = W - 2 * mx - 2 * pad
    meas = ImageDraw.Draw(img)

    def body(d, y, measure):
        if not measure:
            badge(d, mx + pad, y, "오늘의 핵심 표현", ACCENT, font("Bold", 30))
        y += 84
        for k in s["key_phrases"]:
            y = text_block(d, mx + pad, y, k["en"], font("Bold", 42), INK, max_w, measure=measure)
            y = text_block(d, mx + pad, y, k["ko"], font("Regular", 31), SUB, max_w, measure=measure) + 26
        if not measure:
            d.line((mx + pad, y, W - mx - pad, y), fill=(230, 230, 235), width=2)
        y += 26
        y = text_block(d, mx + pad, y, "TIP  " + s["tip"], font("Bold", 32), ACCENT, max_w, measure=measure) + 18
        y = text_block(d, mx + pad, y, "저장해두고 여행 갈 때 꺼내 보세요!", font("Bold", 32), INK, max_w, measure=measure)
        return y

    h = body(meas, 0, True) + 2 * pad
    top = max(110, (H - h) // 2)
    img = overlay(img, (mx, top, W - mx, top + h), (255, 255, 255, 242), 44)
    d = ImageDraw.Draw(img)
    footer(d, s["episode"], total, total)
    body(d, top + pad, False)
    img.convert("RGB").save(out, optimize=True)


# ---------- main ----------

def main():
    ep_dir = sys.argv[1].rstrip("/")
    compose_only = "--compose" in sys.argv
    force = "--force" in sys.argv
    s = json.load(open(f"{ep_dir}/script.json", encoding="utf-8"))
    os.makedirs(f"{ep_dir}/raw", exist_ok=True)
    os.makedirs(f"{ep_dir}/final", exist_ok=True)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    report = [f"# #{s['episode']} 「{s['title']}」 렌더링 결과", "", f"- 실행 시각: {kst}"]

    total = len(s["panels"]) + 2
    jobs = [(1, s["cover_scene"], False)] + [(p["cut"], p["scene"], True) for p in s["panels"]] \
        + [(total, s["summary_scene"], False)]
    for n, scene, safe in jobs:
        raw = f"{ep_dir}/raw/cut{n}.png"
        if not compose_only and (force or not os.path.exists(raw)):
            img, model, err = generate_photo(key, scene, safe)
            if not img:
                report.append(f"- {n}장: ❌ {err}")
                continue
            open(raw, "wb").write(img)
            report.append(f"- {n}장: ✅ 사진 생성 ({model})")
        if not os.path.exists(raw):
            continue
        out = f"{ep_dir}/final/{n:02d}.png"
        if n == 1:
            compose_cover(raw, s, out, total)
        elif n == total:
            compose_summary(raw, s, out, total)
        else:
            compose_dialogue(raw, s, next(p for p in s["panels"] if p["cut"] == n), out, total)
        report.append(f"- {n}장: ✅ 합성")

    open(f"{ep_dir}/report.md", "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
