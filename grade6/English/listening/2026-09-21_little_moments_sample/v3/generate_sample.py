#!/usr/bin/env python3
"""Synthesize the pilot with distinct actors and assemble aligned subtitles."""
import asyncio
import hashlib
import html
import json
import re
import subprocess
import wave
from pathlib import Path
import edge_tts

BASE = Path(__file__).resolve().parent
CACHE = Path("/tmp/little-bear-life-v3-clips")
CACHE.mkdir(parents=True, exist_ok=True)
GAP = 0.12


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def normalize(s):
    return re.sub(r"[^a-z0-9]", "", html.unescape(s).lower())


def stamp(s):
    ms = round(s * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


async def clip(index, part, cast, semaphore):
    actor = cast[part["speaker"]]
    signature = hashlib.sha256(json.dumps(
        [part, actor, edge_tts.__version__], sort_keys=True).encode()).hexdigest()
    audio = CACHE / (signature + ".mp3")
    meta = CACHE / (signature + ".json")
    async with semaphore:
        if not (audio.exists() and meta.exists()):
            for attempt in range(3):
                try:
                    cues = []
                    comm = edge_tts.Communicate(
                        part["text"], actor["voice"], rate=actor["rate"],
                        pitch=actor["pitch"], boundary="SentenceBoundary")
                    with audio.with_suffix(".partial.mp3").open("wb") as out:
                        async for chunk in comm.stream():
                            if chunk["type"] == "audio":
                                out.write(chunk["data"])
                            elif chunk["type"] == "SentenceBoundary":
                                cues.append({"start": chunk["offset"]/1e7,
                                             "end": (chunk["offset"]+chunk["duration"])/1e7,
                                             "text": chunk["text"]})
                    assert normalize(" ".join(c["text"] for c in cues)) == normalize(part["text"])
                    audio.with_suffix(".partial.mp3").replace(audio)
                    meta.write_text(json.dumps(cues, ensure_ascii=False))
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 * (attempt + 1))
        wav = CACHE / (signature + ".wav")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(audio),
             "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        with wave.open(str(wav)) as reader:
            frames = reader.readframes(reader.getnframes())
            duration = reader.getnframes() / reader.getframerate()
        cues = json.loads(meta.read_text())
        for i, cue in enumerate(cues):
            next_start = cues[i+1]["start"] if i+1 < len(cues) else duration
            cue["end"] = min(cue["end"], next_start, duration)
            assert 0 <= cue["start"] < cue["end"] <= duration
        print(f'CLIP {index+1:02d} {part["speaker"]}: {duration:.2f}s', flush=True)
        return {"frames": frames, "duration": duration, "cues": cues,
                "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                "speaker": part["speaker"], "voice": actor["voice"]}


async def main():
    script = json.loads((BASE / "script.json").read_text())
    cast, parts = script["cast"], script["segments"]
    expected = (BASE / "sample.txt").read_text()
    assert normalize(" ".join(p["text"] for p in parts)) == normalize(expected)
    voice_list = {v["ShortName"]: v for v in await edge_tts.list_voices()}
    assert len(set(a["voice"] for a in cast.values())) == 4
    for actor in cast.values():
        assert voice_list[actor["voice"]]["Locale"] == "en-US"
    semaphore = asyncio.Semaphore(3)
    clips = await asyncio.gather(*(clip(i, p, cast, semaphore)
                                  for i, p in enumerate(parts)))
    joined = CACHE / "assembled.wav"
    cursor = 0.0
    cues, turns = [], []
    silence = b"\x00\x00" * round(24000 * GAP)
    with wave.open(str(joined), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        for i, item in enumerate(clips):
            writer.writeframes(item["frames"])
            start = cursor
            for cue in item["cues"]:
                cues.append({**cue, "start": cursor+cue["start"],
                             "end": cursor+cue["end"]})
            cursor += item["duration"]
            turns.append({"speaker": item["speaker"], "voice": item["voice"],
                          "start": start, "end": cursor,
                          "clip_sha256": item["sha256"]})
            if i+1 < len(clips):
                writer.writeframes(silence)
                cursor += GAP
    target = BASE / "sample_v3_cast.mp3"
    partial = target.with_suffix(".partial.mp3")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-af",
         "loudnorm=I=-18:TP=-2:LRA=9", "-ar", "24000", "-ac", "1",
         "-c:a", "libmp3lame", "-b:a", "64k", str(partial)])
    duration = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", str(partial)]).stdout)
    assert 30 < duration < 1200
    assert abs(duration-cursor) < 0.2
    assert normalize(" ".join(c["text"] for c in cues)) == normalize(expected)
    assert all(a["end"] <= b["start"] for a, b in zip(cues, cues[1:]))
    check = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(partial),
                 "-af", "silencedetect=noise=-50dB:d=3,volumedetect",
                 "-f", "null", "-"])
    assert "silence_duration:" not in check.stderr
    peak = float(re.search(r"max_volume: ([-\d.]+) dB", check.stderr)[1])
    assert peak < 0
    partial.replace(target)
    (BASE / "sample_v3_cast.srt").write_text("\n\n".join(
        f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}'
        for i, c in enumerate(cues)) + "\n")
    words = len(re.findall(r"\b\w+(?:'\w+)?\b", expected))
    receipt = {
        "status": "SAMPLE_AWAITING_USER_FEEDBACK", "engine": "edge-tts",
        "engine_version": edge_tts.__version__, "cast": cast,
        "voice_metadata": {k: voice_list[v["voice"]] for k,v in cast.items()},
        "duration_seconds": duration, "word_count": words,
        "words_per_minute_including_pauses": round(words*60/duration, 1),
        "speaker_turns": turns, "turn_gap_seconds": GAP,
        "audio_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256((BASE/"script.json").read_bytes()).hexdigest(),
        "checks": {"full_decode": "passed", "four_distinct_us_voices": True,
                   "subtitle_full_text_match": True, "peak_db": peak,
                   "silence_over_3_seconds": False},
        "human_listening_review": "not_performed",
        "notes": "Lucy also narrates in first person; Dad, clerk, and Ben each use a different voice. Voice ages are not specified by provider."
    }
    (BASE/"generation_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({k:receipt[k] for k in
                      ["duration_seconds","word_count","words_per_minute_including_pauses","checks"]},indent=2))


if __name__ == "__main__":
    asyncio.run(main())
