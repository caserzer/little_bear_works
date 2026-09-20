#!/usr/bin/env python3
"""Render the original Curiosity Club scripts, synthesize MP3/SRT, and audit audio.

Use the isolated environment documented in the listening README. Only original
English narration is sent to Edge TTS. Student homework and personal data stay local.
"""
import argparse
import asyncio
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'grade6/English/listening/2026-09-20_curiosity_club'


def episodes():
    result = []
    for path in sorted((BASE / 'content').glob('*.json')):
        result.extend(json.loads(path.read_text()))
    result.sort(key=lambda e: e['id'])
    assert len({e['id'] for e in result}) == len(result)
    return result


def stem(e):
    return f"{e['id']:02d}_" + re.sub(r'[^a-z0-9]+', '_', e['title'].lower()).strip('_')


def settings(e):
    return ('en-US-JennyNeural' if e['id'] % 2 else 'en-US-GuyNeural',
            '-12%' if e['id'] <= 16 else '-8%')


def narration(e):
    phrases = '\n\n'.join(f'{p}\n{p}' for p in e['phrases'])
    return (f"The Curiosity Club. Episode {e['id']}. {e['title']}.\n\n"
            f"Here is something to listen for. {e['question']}\n\n"
            f"Ready? Let us find out.\n\n{e['story']}\n\n"
            f"Now, a little more to discover.\n\n{e['fact']}\n\n"
            f"Let us hear the main idea again.\n\n{e['recap']}\n\n"
            f"Here are three useful expressions. You can listen, or say them with me.\n\n{phrases}\n\n"
            f"Remember our listening question? {e['question']}\n\n"
            f"Here is the answer. {e['answer']}\n\n"
            f"And here is a question just for your imagination. {e['wonder']}\n\n"
            "There is more than one possible answer. Keep wondering, and see you next time.")


def prepare(e):
    for d in ['audio', 'transcripts', 'subtitles', 'receipts']:
        (BASE / d).mkdir(parents=True, exist_ok=True)
    name = stem(e)
    speech = narration(e)
    (BASE / 'transcripts' / f'{name}.txt').write_text(speech + '\n')
    voice, rate = settings(e)
    vocab = '\n'.join(f'| {w} | {meaning} |' for w, meaning in e['words'].items())
    sources = '\n'.join(f'- [知识核对来源 {i+1}]({url})' for i, url in enumerate(e['sources']))
    if not sources:
        sources = '本集为原创情境，知识点为基础常识或故事内部的观察；不冒充真实事件。'
    text = (f"# {e['id']:02d} · {e['title_zh']}\n\n## {e['title']}\n\n"
            f"{e['summary_zh']}\n\n语言接触重点：{e['focus']}。\n\n"
            f"[播放 MP3](../audio/{name}.mp3) · [英文字幕](../subtitles/{name}.srt)\n\n"
            "## 听前可看三个词\n\n| 英文 | 中文提示 |\n|---|---|\n"
            f"{vocab}\n\n## 完整音频原文\n\n{speech}\n\n"
            f"## 资料说明\n\n故事、人物和对话为原创虚构；科普说明与情节分开。"
            f"AI合成美式旁白：{voice}，语速参数 {rate}。\n\n{sources}\n")
    (BASE / 'transcripts' / f'{name}.md').write_text(text)
    return speech


def duration(path):
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                       check=True, capture_output=True, text=True)
    return float(p.stdout)


def clean_subtitles(srt):
    """Clamp small service boundary overlaps without shifting sentence starts."""
    blocks = srt.strip().split('\n\n')
    for index in range(len(blocks) - 1):
        lines = blocks[index].splitlines()
        following = blocks[index + 1].splitlines()
        start, end = lines[1].split(' --> ')
        next_start = following[1].split(' --> ')[0]
        if end > next_start:
            assert next_start >= start
            lines[1] = start + ' --> ' + next_start
            blocks[index] = '\n'.join(lines)
    return '\n\n'.join(blocks) + '\n'


async def synthesize(e, semaphore):
    import edge_tts
    async with semaphore:
        speech = prepare(e)
        name = stem(e)
        mp3 = BASE / 'audio' / f'{name}.mp3'
        srt = BASE / 'subtitles' / f'{name}.srt'
        receipt = BASE / 'receipts' / f'{name}.json'
        voice, rate = settings(e)
        signature = hashlib.sha256((speech + voice + rate).encode()).hexdigest()
        if mp3.exists() and srt.exists() and receipt.exists():
            old = json.loads(receipt.read_text())
            if old.get('input_sha256') == signature and old.get('audio_sha256') == hashlib.sha256(mp3.read_bytes()).hexdigest():
                print(f'SKIP {name}', flush=True)
                return
        for attempt in range(4):
            part = mp3.with_suffix('.partial.mp3')
            try:
                communicate = edge_tts.Communicate(speech, voice, rate=rate, boundary='SentenceBoundary')
                subs = edge_tts.SubMaker()
                with part.open('wb') as out:
                    async for chunk in communicate.stream():
                        if chunk['type'] == 'audio':
                            out.write(chunk['data'])
                        elif chunk['type'] in ('SentenceBoundary', 'WordBoundary'):
                            subs.feed(chunk)
                length = duration(part)
                assert 30 < length < 1200, f'Invalid duration: {length}'
                subprocess.run(['ffmpeg', '-v', 'error', '-i', str(part), '-f', 'null', '-'],
                               check=True, capture_output=True)
                subtitle = clean_subtitles(subs.get_srt())
                assert subtitle.strip(), 'Missing subtitles'
                part.replace(mp3)
                srt.write_text(subtitle)
                count = len(re.findall(r"\b[\w]+(?:'[\w]+)?\b", speech))
                receipt.write_text(json.dumps({
                    'id': e['id'], 'title': e['title'], 'title_zh': e['title_zh'],
                    'engine': 'edge-tts', 'engine_version': edge_tts.__version__,
                    'voice': voice, 'locale': 'en-US', 'rate': rate,
                    'duration_seconds': length, 'word_count': count,
                    'words_per_minute_including_pauses': round(count * 60 / length, 1),
                    'input_sha256': signature,
                    'audio_sha256': hashlib.sha256(mp3.read_bytes()).hexdigest(),
                    'decode_check': 'passed', 'human_listening_check': 'not_performed',
                    'audio': f'audio/{name}.mp3', 'transcript': f'transcripts/{name}.md',
                    'subtitle': f'subtitles/{name}.srt',
                }, ensure_ascii=False, indent=2) + '\n')
                print(f'OK {name}: {length:.1f}s', flush=True)
                return
            except Exception as exc:
                print(f'RETRY {name} {attempt+1}: {type(exc).__name__}: {exc}', flush=True)
                if attempt == 3:
                    raise
                await asyncio.sleep(3 * (attempt + 1))


def catalog():
    all_e = episodes()
    entries = []
    for e in all_e:
        receipt = BASE / 'receipts' / f'{stem(e)}.json'
        if receipt.exists():
            entries.append({**e, **json.loads(receipt.read_text()), 'speech': narration(e)})
    (BASE / 'catalog.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
    (BASE / '全部音频.m3u8').write_text('#EXTM3U\n' + ''.join(
        f"#EXTINF:{round(e['duration_seconds'])},{e['id']:02d} {e['title']}\n{e['audio']}\n" for e in entries))
    data = json.dumps(entries, ensure_ascii=False).replace('</', '<\\/')
    template = (ROOT / 'scripts/templates/english_listening_player.html').read_text()
    (BASE / '播放.html').write_text(template.replace('__EPISODES__', data))
    rows = []
    for e in entries:
        seconds = round(e['duration_seconds'])
        rows.append(f"| {e['id']:02d} | [{e['title_zh']}]({e['audio']}) | {e['title']} | {seconds//60}:{seconds%60:02d} | [{e['category']}]({e['transcript']}) |")
    total = sum(e['duration_seconds'] for e in entries)
    (BASE / '目录.md').write_text(
        '# 好奇心俱乐部 · 音频目录\n\n'
        f'已完成 {len(entries)} 集，共 {total/60:.1f} 分钟。美式英语合成旁白。\n\n'
        '[离线播放器](播放.html) · [使用说明](README.md) · [连续播放列表](全部音频.m3u8)\n\n'
        '| 集数 | 中文标题／音频 | English title | 实测时长 | 分类／原文 |\n|---|---|---|---|---|\n'
        + '\n'.join(rows) + '\n')
    print(f'CATALOG {len(entries)}/{len(all_e)}; {total/60:.1f} minutes', flush=True)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', help='Inclusive range such as 1-8')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--catalog-only', action='store_true')
    parser.add_argument('--concurrency', type=int, default=2)
    args = parser.parse_args()
    if args.catalog_only:
        catalog()
        return
    selected = episodes()
    if args.ids:
        lo, hi = map(int, args.ids.split('-'))
        selected = [e for e in selected if lo <= e['id'] <= hi]
    for e in selected:
        prepare(e)
    if not args.prepare_only:
        sem = asyncio.Semaphore(args.concurrency)
        await asyncio.gather(*(synthesize(e, sem) for e in selected))
    if (ROOT / 'scripts/templates/english_listening_player.html').exists():
        catalog()


if __name__ == '__main__':
    asyncio.run(main())
