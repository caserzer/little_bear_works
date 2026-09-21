#!/usr/bin/env python3
"""Generate only the requested pilot; the new 40-episode season awaits feedback."""
import asyncio
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path

import edge_tts

BASE = Path(__file__).resolve().parent
VOICE = "en-US-MichelleNeural"
RATE = "+20%"
PITCH = "+0Hz"


def clean_srt(srt):
    blocks = srt.strip().split("\n\n")
    for i in range(len(blocks) - 1):
        lines = blocks[i].splitlines()
        start, end = lines[1].split(" --> ")
        next_start = blocks[i + 1].splitlines()[1].split(" --> ")[0]
        if end > next_start:
            assert next_start >= start
            lines[1] = start + " --> " + next_start
            blocks[i] = "\n".join(lines)
    return "\n\n".join(blocks) + "\n"


async def main():
    text = (BASE / "sample.txt").read_text().strip()
    voices = await edge_tts.list_voices()
    voice_info = next(v for v in voices if v["ShortName"] == VOICE)
    assert voice_info["Locale"] == "en-US"
    mp3 = BASE / "sample_v2_one_more_please.mp3"
    partial = mp3.with_suffix(".partial.mp3")
    sub = edge_tts.SubMaker()
    communication = edge_tts.Communicate(
        text, VOICE, rate=RATE, pitch=PITCH, boundary="SentenceBoundary"
    )
    with partial.open("wb") as output:
        async for chunk in communication.stream():
            if chunk["type"] == "audio":
                output.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                sub.feed(chunk)
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(partial)],
        check=True, capture_output=True, text=True).stdout)
    assert 30 < duration < 1200
    check = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(partial), "-af",
         "silencedetect=noise=-50dB:d=3,volumedetect", "-f", "null", "-"],
        check=True, capture_output=True, text=True)
    assert "silence_duration:" not in check.stderr
    peak = float(re.search(r"max_volume: ([-\d.]+) dB", check.stderr)[1])
    assert peak < 0
    srt = clean_srt(sub.get_srt())
    lines = [line for line in srt.splitlines()
             if line.strip() and not line.strip().isdigit() and "-->" not in line]
    normalize = lambda s: re.sub(r"[^a-z0-9]", "", html.unescape(s).lower())
    assert normalize(" ".join(lines)) == normalize(text), "Subtitle/text mismatch"
    times = re.findall(r"(\d\d):(\d\d):(\d\d),(\d{3})", srt)
    h, m, s, ms = map(int, times[-1])
    subtitle_end = h * 3600 + m * 60 + s + ms / 1000
    assert -0.5 <= duration - subtitle_end < 4, f"Duration {duration}; subtitle ending {subtitle_end}"
    if subtitle_end > duration:
        blocks = srt.strip().split("\n\n")
        lines = blocks[-1].splitlines()
        ms_total = int(duration * 1000)
        h, rem = divmod(ms_total, 3600000)
        m, rem = divmod(rem, 60000)
        seconds, millis = divmod(rem, 1000)
        end = f"{h:02d}:{m:02d}:{seconds:02d},{millis:03d}"
        lines[1] = lines[1].split(" --> ")[0] + " --> " + end
        blocks[-1] = "\n".join(lines)
        srt = "\n\n".join(blocks) + "\n"
    partial.replace(mp3)
    (BASE / "sample_v2_one_more_please.srt").write_text(srt)
    count = len(re.findall(r"\b\w+(?:'\w+)?\b", text))
    receipt = {
        "status": "SAMPLE_AWAITING_USER_FEEDBACK",
        "title": "One More, Please!", "title_zh": "再来一个，谢谢！",
        "engine": "edge-tts", "engine_version": edge_tts.__version__,
        "voice": voice_info, "rate": RATE, "pitch": PITCH,
        "duration_seconds": duration, "word_count": count,
        "words_per_minute_including_pauses": round(count * 60 / duration, 1),
        "audio_sha256": hashlib.sha256(mp3.read_bytes()).hexdigest(),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "checks": {"full_decode": "passed", "subtitle_full_text_match": True,
                   "peak_db": peak, "silence_over_3_seconds": False},
        "human_listening_review": "not_performed",
        "new_season_episodes_generated": 1,
        "notes": "Single synthetic American female narrator, targeting a youthful natural sound; perceived age is not guaranteed. Faster revision requested by user; all characters share one voice."
    }
    (BASE / "generation_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in
                      ["status", "duration_seconds", "word_count",
                       "words_per_minute_including_pauses", "checks"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
