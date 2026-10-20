"""완성된 6장 슬라이드 + 원어민 음성(Kokoro TTS)으로 릴스 영상(mp4) 만들기.

사용법: python scripts/make_reel.py episodes/ep002 [--silent]
  --silent : TTS 없이 무음 테스트 (로컬 레이아웃 확인용)

구성 (장마다 해당 음성이 끝날 때까지 화면 유지)
  1장 표지    : 짧은 효과 없이 2.5초
  2~5장 대화  : 직원 대사(남성 목소리) → 나 대사(여성 목소리)
  6장 정리    : 핵심 표현을 여성 목소리로 천천히 한 번씩
출력: <ep>/reel.mp4 (1080x1920, H.264 + AAC, 30fps)
"""
import json
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageFilter

W, H = 1080, 1920
SR = 24000
VOICE_STAFF = os.environ.get("REEL_VOICE_STAFF", "am_michael")   # 미국 남성
VOICE_ME = os.environ.get("REEL_VOICE_ME", "af_heart")            # 미국 여성
GAP = 0.45      # 대사 사이 쉼
TAIL = 0.9      # 장 끝 여유
COVER_SEC = 2.5

_pipe = None


def tts(text, voice, speed=1.0):
    """Kokoro로 문장을 읽은 float32 오디오(24kHz) 반환."""
    global _pipe
    if _pipe is None:
        from kokoro import KPipeline
        _pipe = KPipeline(lang_code="a")  # American English
    chunks = [a for _, _, a in _pipe(text, voice=voice, speed=speed)]
    return np.concatenate([np.asarray(c, dtype=np.float32) for c in chunks]) if chunks else np.zeros(0, np.float32)


def silence(sec):
    return np.zeros(int(SR * sec), dtype=np.float32)


def write_wav(path, audio):
    peak = float(np.max(np.abs(audio))) if len(audio) else 0
    if peak > 0:
        audio = audio * (0.9 / peak)  # 음량을 일정하게 키움 (휴대폰 스피커에서도 잘 들리게)
    a = np.clip(audio, -1, 1)
    pcm = (a * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def frame(slide_path, out_path):
    """4:5 슬라이드를 9:16 화면에: 흐린 배경 위에 원본을 가운데 배치."""
    sl = Image.open(slide_path).convert("RGB")
    bg = sl.resize((W, int(W * sl.height / sl.width))).resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
    fg = sl.resize((W, int(W * sl.height / sl.width)), Image.LANCZOS)
    bg.paste(fg, (0, (H - fg.height) // 2))
    bg.save(out_path, quality=95)


def main():
    ep = sys.argv[1].rstrip("/")
    silent = "--silent" in sys.argv
    s = json.load(open(f"{ep}/script.json", encoding="utf-8"))
    me = next(iter(json.load(open("config/series.json", encoding="utf-8"))["characters"]))
    slides = sorted(f for f in os.listdir(f"{ep}/final") if f.endswith(".png"))
    total = len(s["panels"]) + 2
    if len(slides) < total:
        raise SystemExit(f"슬라이드가 {len(slides)}장뿐이에요 (필요: {total})")

    def say(text, voice, speed=1.0, est=0.075):
        if silent:  # 단어 수로 길이만 흉내
            return silence(max(1.0, len(text.split()) * est / speed * 5))
        return tts(text, voice, speed)

    segs = []  # (이미지, 오디오)
    segs.append((f"{ep}/final/{slides[0]}", silence(COVER_SEC)))
    for p in s["panels"]:
        audio = [silence(0.35)]
        for d in p["dialogues"]:
            audio += [say(d["en"], VOICE_ME if d["speaker"] == me else VOICE_STAFF), silence(GAP)]
        audio.append(silence(TAIL))
        segs.append((f"{ep}/final/{p['cut']:02d}.png", np.concatenate(audio)))
    audio = [silence(0.4)]
    for k in s["key_phrases"]:
        audio += [say(k["en"], VOICE_ME, speed=0.85), silence(0.8)]
    audio.append(silence(1.2))
    segs.append((f"{ep}/final/{slides[-1]}", np.concatenate(audio)))

    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (img, aud) in enumerate(segs):
            fimg, fwav, fmp4 = f"{tmp}/f{i}.jpg", f"{tmp}/a{i}.wav", f"{tmp}/p{i}.mp4"
            frame(img, fimg)
            write_wav(fwav, aud)
            dur = len(aud) / SR
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", fimg, "-i", fwav,
                "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage",
                "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                "-shortest", fmp4], check=True)
            parts.append(fmp4)
        with open(f"{tmp}/list.txt", "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{tmp}/list.txt",
                        "-c", "copy", "-movflags", "+faststart", f"{ep}/reel.mp4"], check=True)
    secs = sum(len(a) for _, a in segs) / SR
    print(f"✅ {ep}/reel.mp4 ({secs:.1f}초, {os.path.getsize(f'{ep}/reel.mp4') // 1024}KB)")


if __name__ == "__main__":
    main()
