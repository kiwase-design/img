"""여행영어 한 편 렌더링: Pixabay 무료 사진 → 반투명 자막 카드 합성(Pillow).

사용법:
  python scripts/render_episode.py episodes/ep001            # 없는 사진만 받아오기 + 전체 합성
  python scripts/render_episode.py episodes/ep001 --force    # 사진 전부 새로 고르기
  python scripts/render_episode.py episodes/ep001 --compose  # 합성만

산출물:
  <ep>/raw/cutN.jpg     Pixabay 원본 사진 (1=표지, 2~5=대화, 6=정리)
  <ep>/credits.json     장별 사진 출처 (작가, 페이지)
  <ep>/final/NN.png     인스타 업로드용 1080x1350
"""
import base64
import glob
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
NOTO = "/usr/share/fonts/opentype/noto/NotoSansCJK-{}.ttc"
SERIES = json.load(open("config/series.json", encoding="utf-8"))
HERO_ID = next(iter(SERIES["characters"]))
HERO = SERIES["characters"][HERO_ID]
PIXABAY = "https://pixabay.com/api/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; travel-english-bot/1.0; +https://github.com/kiwase-design/img)"}

ACCENT = (255, 94, 98)      # 여행자(나) 라벨
STAFF = (70, 110, 160)      # 상대방 라벨
INK = (25, 25, 30)
SUB = (95, 95, 105)


def font(weight, size):
    return ImageFont.truetype(NOTO.format(weight), size, index=1)


# ---------- 사진 가져오기 ----------

def used_photo_ids():
    """이미 쓴 사진 id — 편끼리 같은 사진이 반복되지 않게."""
    ids = set()
    for p in glob.glob("episodes/ep*/credits.json"):
        try:
            ids |= {c["id"] for c in json.load(open(p, encoding="utf-8")).values()}
        except Exception:
            pass
    return ids


def search_pixabay(key, query, orientation):
    params = urllib.parse.urlencode({
        "key": key, "q": query[:100], "image_type": "photo", "orientation": orientation,
        "safesearch": "true", "per_page": 40, "min_width": 1000, "order": "popular",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{PIXABAY}?{params}", headers=UA), timeout=60) as r:
                return json.loads(r.read()).get("hits", [])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:  # 분당 100회 제한 → 잠시 쉬었다 재시도
                time.sleep(int(e.headers.get("X-RateLimit-Reset", "30") or 30) + 2)
                continue
            body = e.read().decode("utf-8", "ignore")[:200]
            raise RuntimeError(f"Pixabay HTTP {e.code}: {body}") from None


STOP = {"in", "at", "the", "a", "an", "of", "and", "with", "on", "to", "for"}


def relevance(hit, words):
    """사진 태그에 검색어 단어가 몇 개나 들어있는지 (단어 앞부분 일치, 복수형 허용)."""
    tags = [t.strip() for t in hit.get("tags", "").lower().split(",")]
    tagwords = {w for t in tags for w in t.split()}
    score = 0
    for w in words:
        if any(tw == w or tw.startswith(w[:5]) for tw in tagwords):
            score += 1
    return score


def download(hit):
    """사진 파일 내려받기. 너무 빨리 받으면 429가 나서 쉬었다 재시도, 그래도 안 되면 작은 크기로."""
    for attempt, url in enumerate([hit["largeImageURL"]] * 4 + [hit["webformatURL"]]):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("사진 다운로드 429 반복")


def main_subject_ok(hit, word):
    """검색어 첫 단어(핵심 대상)가 사진의 대표 태그(앞쪽 3개)에 들어 있어야 함."""
    top = [t.strip() for t in hit.get("tags", "").lower().split(",")[:3]]
    return any(word[:5] in t for t in top)


PEOPLE = {"woman", "women", "girl", "man", "men", "boy", "portrait", "model", "beauty", "fashion",
          "person", "lady", "female", "male", "face", "selfie", "pretty", "young woman"}
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models"


def people_heavy(hit):
    top = [t.strip() for t in hit.get("tags", "").lower().split(",")[:4]]
    return any(t in PEOPLE or t.split()[-1] in PEOPLE for t in top)


PICK_LOG = []


def get_bytes(url, tries=4):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or a == tries - 1:
                raise
            time.sleep(8 * (a + 1))


def gemini_pick(cands, context, query):
    """Gemini(텍스트 모델, 저렴)가 후보 미리보기를 직접 보고 가장 알맞은 사진 번호를 고른다. 실패하면 None."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        PICK_LOG.append("GEMINI_API_KEY 없음")
        return None
    parts, fails = [], 0
    for i, h in enumerate(cands[:4]):
        try:
            data = get_bytes(h["webformatURL"])
            parts.append({"text": f"Photo {i}:"})
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(data).decode()}})
        except Exception as e:
            fails += 1
            PICK_LOG.append(f"미리보기 실패 {type(e).__name__} {e}")
        time.sleep(2.5)
    if not parts:
        return None
    parts.append({"text": (
        f"These are stock photo candidates for one slide of an Instagram post teaching travel English.\n"
        f"Slide topic: {context}\nSearch words: {query}\n"
        "Pick the ONE photo that best illustrates this exact situation. REJECT photos that: "
        "show readable brand names, airline/company logos or big readable text; "
        "are mainly a posed portrait of a person or a model; are unrelated to the situation (wrong place). "
        'Answer JSON only: {"best": <photo number>} or {"best": -1} if none is acceptable.')})
    model = os.environ.get("GEMINI_VISION_MODEL", "")
    models = [model] if model else ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3-flash", "gemini-2.5-flash"]
    for m in models:
        req = urllib.request.Request(
            f"{GEMINI}/{m}:generateContent", method="POST",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            data=json.dumps({"contents": [{"parts": parts}],
                             "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}).encode())
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read())
                txt = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
                return int(json.loads(txt)["best"])
            except urllib.error.HTTPError as e:
                PICK_LOG.append(f"Gemini {m} HTTP {e.code}")
                if e.code in (429, 500, 503) and attempt < 2:  # 일시적 과부하 → 잠시 후 재시도
                    time.sleep(15 * (attempt + 1))
                    continue
                break  # 404 등 → 다음 모델
            except Exception as e:
                PICK_LOG.append(f"Gemini {m} 응답 오류 {type(e).__name__} {e}")
                return None
    return None


def fetch_photo(key, query, avoid, context=""):
    """검색어로 후보를 모으고, Gemini가 직접 보고 고르게 한다 (실패 시 태그 점수로). 안 맞으면 검색어를 줄여 재검색."""
    words = [w for w in query.lower().split() if w not in STOP]
    tries = [" ".join(words)]
    if len(words) > 2:
        tries.append(" ".join(words[:2]))
    if len(words) > 1:
        tries += [" ".join(words[i:i + 2]) for i in range(1, len(words) - 1)]
    for q in tries:
        qw = q.split()
        need = len(qw) if len(qw) <= 2 else len(qw) - 1
        hits = []
        for ori in ("vertical", "all"):
            hits = [h for h in search_pixabay(key, q, ori) if h["id"] not in avoid and not people_heavy(h)]
            hits = [h for h in hits if relevance(h, qw) >= need and main_subject_ok(h, qw[0])]
            if len(hits) >= 4:
                break
        if not hits:
            continue
        hits.sort(key=lambda h: (relevance(h, words), h.get("likes", 0)), reverse=True)
        cands = hits[:8]
        random.shuffle(cands)  # '그림 다시' 때 다른 사진이 뽑히게
        best = gemini_pick(cands, context, q)
        if best == -1:
            continue  # 쓸 만한 게 없음 → 다음 검색어
        h = cands[best] if best is not None and 0 <= best < len(cands) else cands[0]
        data = download(h)
        time.sleep(2)
        return data, {"id": h["id"], "user": h["user"], "page": h["pageURL"], "query": q,
                      "tags": h.get("tags", ""), "picked_by": "gemini" if best is not None else "tags"}
    return None, None


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


def overlay(img, box, fill, radius=36, blur=14):
    """배경이 비쳐 보이는 반투명 유리 카드: 카드 영역만 살짝 흐리게 + 반투명 흰색."""
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    if blur:
        img = Image.composite(img.filter(ImageFilter.GaussianBlur(blur)), img, mask)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=fill, outline=(255, 255, 255, 170), width=2)
    return Image.alpha_composite(img, layer)


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
    img = overlay(img, (mx, top, W - mx, H - 48), (255, 255, 255, 150))
    d = ImageDraw.Draw(img)
    footer(d, s["episode"], panel["cut"], total)
    y = top + pad
    for i, dl in enumerate(panel["dialogues"]):
        hero = dl["speaker"] == HERO_ID
        badge(d, mx + pad, y, HERO["name"] if hero else s.get("other_label", "직원"), ACCENT if hero else STAFF, f_lb)
        y += 54
        y = text_block(d, mx + pad, y, dl["en"], f_en, INK, max_w)
        y = text_block(d, mx + pad, y + 2, dl["ko"], f_ko, SUB, max_w) + 22
        if i == 0:
            d.line((mx + pad, y - 12, W - mx - pad, y - 12), fill=(225, 225, 230), width=2)
    img.convert("RGB").save(out, optimize=True)


def compose_summary(raw, s, out, total):
    img = fit_cover(Image.open(raw)).convert("RGBA")
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
    img = overlay(img, (mx, top, W - mx, top + h), (255, 255, 255, 165), 44, blur=10)
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
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    report = [f"# #{s['episode']} 「{s['title']}」 렌더링 결과", "", f"- 실행 시각: {kst}"]
    cpath = f"{ep_dir}/credits.json"
    credits = json.load(open(cpath, encoding="utf-8")) if os.path.exists(cpath) else {}
    avoid = used_photo_ids()

    total = len(s["panels"]) + 2
    def ctx(p):
        return f"{s.get('topic', '')} — " + " / ".join(d["en"] for d in p["dialogues"])
    jobs = [(1, s["cover_query"], f"Cover photo for: {s.get('topic', s['title'])} (an attractive wide photo of the place)")] \
        + [(p["cut"], p["photo_query"], ctx(p)) for p in s["panels"]] \
        + [(total, s["summary_query"], "Calm simple background for a summary slide (travel mood)")]
    for n, query, context in jobs:
        raw = f"{ep_dir}/raw/cut{n}.jpg"
        if not compose_only and (force or not os.path.exists(raw)):
            try:
                img, cred = fetch_photo(key, query, avoid, context)
            except (urllib.error.HTTPError, RuntimeError) as e:
                img, cred = None, None
                report.append(f"- {n}장: ❌ {e}")
            if not img:
                report.append(f"- {n}장: ❌ '{query}' 사진 없음")
                continue
            open(raw, "wb").write(img)
            time.sleep(3)  # 연속 요청 완화
            credits[str(n)] = cred
            avoid.add(cred["id"])
            report.append(f"- {n}장: ✅ 사진 ({cred['query']} · {cred['user']} · {cred['picked_by']})")
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

    if PICK_LOG:
        report += ["", "## 사진 선택 로그"] + [f"- {x}" for x in PICK_LOG[:30]]
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=2)
    with open(f"{ep_dir}/report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
