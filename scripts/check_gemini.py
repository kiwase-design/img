"""Gemini API 키 동작 확인 스크립트.

키 값은 절대 출력하지 않고, 결과만 checks/gemini_check.md 에 기록한다.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://generativelanguage.googleapis.com/v1beta"
OUT = "checks/gemini_check.md"


def call(method, path, key, body=None):
    req = urllib.request.Request(
        f"{BASE}/{path}",
        method=method,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def main():
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    lines = [f"# Gemini API 점검 결과", "", f"- 실행 시각: {kst}"]
    key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not key:
        lines.append("- 결과: ❌ `GEMINI_API_KEY` 시크릿을 찾지 못함")
        return write(lines)

    # 1) 모델 목록 조회 (키 유효성)
    status, data = call("GET", "models?pageSize=1000", key)
    if status != 200:
        msg = data.get("error", {}).get("message", "")
        lines.append(f"- 키 확인: ❌ HTTP {status} — {msg}")
        return write(lines)

    models = [m["name"].removeprefix("models/") for m in data.get("models", [])]
    image_models = [m for m in models if "image" in m]
    lines.append(f"- 키 확인: ✅ 정상 (사용 가능 모델 {len(models)}개)")
    lines.append(f"- 이미지 모델: {', '.join(image_models) if image_models else '없음'}")

    # 2) 짧은 텍스트 생성 (실제 호출 가능 여부)
    flashes = sorted((m for m in models if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", m)),
                     key=lambda m: float(m.split("-")[1]), reverse=True)
    text_model = flashes[0] if flashes else None
    if text_model:
        status, data = call(
            "POST", f"models/{text_model}:generateContent", key,
            {"contents": [{"parts": [{"text": "여행 영어 한 문장만 알려줘."}]}]},
        )
        if status == 200:
            try:
                reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                reply = "(응답 형식 확인 필요)"
            lines.append(f"- 텍스트 생성 ({text_model}): ✅ \"{reply[:80]}\"")
        else:
            msg = data.get("error", {}).get("message", "")
            lines.append(f"- 텍스트 생성 ({text_model}): ❌ HTTP {status} — {msg}")

    # 3) 이미지 모델 결제 상태 확인 — 오류 메시지 전문 기록
    for model in ("gemini-3-pro-image", "gemini-3.1-flash-image"):
        status, data = call("POST", f"models/{model}:generateContent", key, {
            "contents": [{"parts": [{"text": "a small red dot on white"}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        })
        if status == 200:
            lines.append(f"- 이미지 생성 ({model}): ✅ 정상")
        else:
            err = data.get("error", {})
            lines.append(f"- 이미지 생성 ({model}): ❌ HTTP {status} / status={err.get('status')}")
            lines.append(f"  - 메시지: {err.get('message', '')}")
            for d in err.get("details", []):
                lines.append(f"  - 상세: {json.dumps(d, ensure_ascii=False)[:600]}")

    write(lines)


def write(lines):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
