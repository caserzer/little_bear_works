#!/usr/bin/env python3
"""Build the approved multi-voice Little Moments collection; resumable per episode."""
import argparse
import asyncio
import hashlib
import html
import json
import re
import subprocess
import wave
import edge_tts
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'grade6/English/listening/2026-09-21_little_moments'
SAMPLE = BASE.parent / '2026-09-21_little_moments_sample/v3'
CACHE = Path('/tmp/little-bear-life-collection')
CACHE.mkdir(exist_ok=True)
CAST = json.loads((BASE / 'cast.json').read_text())


GAP = 0.12
CLIP_CACHE = Path('/tmp/little-bear-life-v3-clips')
CLIP_CACHE.mkdir(exist_ok=True)
CLIP_LOCKS = {}


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
    audio = CLIP_CACHE / (signature + ".mp3")
    meta = CLIP_CACHE / (signature + ".json")
    lock = CLIP_LOCKS.setdefault(signature, asyncio.Lock())
    async with semaphore, lock:
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
        wav = CLIP_CACHE / (signature + ".wav")
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



def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_episodes():
    episodes = json.loads((BASE / 'content/01_bakery.json').read_text())
    for path in sorted((BASE / 'content').glob('*.stories')):
        for block in path.read_text().split('\n===\n'):
            if not block.strip():
                continue
            lines = block.strip().splitlines()
            fields = lines[0].split('|')
            assert len(fields) == 6, (path, fields)
            number, title, chinese, category, summary, focus = fields
            vocab = dict(item.split('=', 1) for item in lines[1].split('|'))
            phrases = lines[2].split('|')
            parts = []
            for line in lines[3:]:
                if not line.strip():
                    continue
                speaker, text = line.split(': ', 1)
                assert speaker in CAST, (path, speaker)
                if parts and parts[-1]['speaker'] == speaker:
                    parts[-1]['text'] += ' ' + text
                else:
                    parts.append({'speaker': speaker, 'text': text})
            episodes.append(dict(id=int(number), title=title, title_zh=chinese,
                                 category=category, summary_zh=summary, focus=focus,
                                 words=vocab, phrases=phrases, segments=parts))
    episodes.sort(key=lambda e:e['id'])
    role_overrides = {4:{'staff':'图书管理员'},9:{'staff':'去程方向司机','clerk':'返程方向司机'},
                      18:{'staff':'老师'},21:{'staff':'学校办公室老师'},
                      24:{'clerk':'理发师'},26:{'clerk':'邻居 Mrs. Lee'},
                      30:{'clerk':'酒店前台'},33:{'staff':'烹饪社老师'}}
    for episode in episodes:
        episode.setdefault('role_names', {}).update(role_overrides.get(episode['id'], {}))
    assert len({e['id'] for e in episodes}) == len(episodes)
    for e in episodes:
        e['slug'] = f"{e['id']:02d}_" + re.sub(r'[^a-z0-9]+', '_', e['title'].lower()).strip('_')
        used = set(p['speaker'] for p in e['segments'])
        assert len(used) >= 2
        assert len({CAST[k]['voice'] for k in used}) == len(used)
        e['cast'] = {k:v for k,v in CAST.items() if k in used}
        e['input_sha256'] = digest(json.dumps([e['segments'],e['cast']],sort_keys=True).encode())
        e['speech'] = '\n\n'.join(p['text'] for p in e['segments'])
        e['word_count'] = len(re.findall(r"\b\w+(?:'\w+)?\b", e['speech']))
        assert 180 <= e['word_count'] <= 450, (e['id'],e['word_count'])
        assert all(p.lower() in e['speech'].lower() for p in e['phrases']), (e['id'],'phrase absent')
    return episodes


def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


async def build_episode(e, metadata, semaphore):
    slug=e['slug']
    target=BASE/'audio'/f'{slug}.mp3'
    subtitle=BASE/'subtitles'/f'{slug}.srt'
    receipt_path=BASE/'receipts'/f'{slug}.json'
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text())
        if target.exists() and digest(target.read_bytes())==receipt['audio_sha256'] and subtitle.exists():
            if e.get('approved_sample'):
                assert digest(target.read_bytes())==digest((SAMPLE/'sample_v3_cast.mp3').read_bytes())
                original=json.loads((SAMPLE/'script.json').read_text())
                assert e['segments']==original['segments']
                receipt['input_sha256']=e['input_sha256']
                write_json(receipt_path,receipt)
                print(f'REUSE APPROVED {slug}',flush=True)
                return
            if receipt.get('input_sha256')==e['input_sha256']:
                print(f'REUSE {slug}',flush=True)
                return
    print(f'BUILD {slug}: {e["word_count"]} words, {len(e["segments"])} turns',flush=True)
    clips=await asyncio.gather(*(clip(i,p,CAST,semaphore) for i,p in enumerate(e['segments'])))
    joined=CACHE/f'{slug}.wav'
    cursor=0.0
    cues,turns=[],[]
    with wave.open(str(joined),'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(24000)
        for i,item in enumerate(clips):
            writer.writeframes(item['frames'])
            for c in item['cues']:
                cues.append({**c,'start':cursor+c['start'],'end':cursor+c['end']})
            turns.append({'speaker':item['speaker'],'voice':item['voice'],'start':cursor,
                          'end':cursor+item['duration'],'clip_sha256':item['sha256']})
            cursor+=item['duration']
            if i+1<len(clips):
                writer.writeframes(b'\0\0'*round(24000*GAP));cursor+=GAP
    partial=target.with_suffix('.partial.mp3')
    run(['ffmpeg','-y','-v','error','-i',str(joined),'-af','loudnorm=I=-18:TP=-2:LRA=9',
               '-ar','24000','-ac','1','-c:a','libmp3lame','-b:a','64k',str(partial)])
    duration=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of',
                             'default=noprint_wrappers=1:nokey=1',str(partial)]).stdout)
    assert 30<duration<1200 and abs(duration-cursor)<0.2
    assert normalize(' '.join(c['text'] for c in cues))==normalize(e['speech'])
    assert all(a['end']<=b['start'] for a,b in zip(cues,cues[1:]))
    check=run(['ffmpeg','-hide_banner','-nostats','-i',str(partial),'-af',
                     'silencedetect=noise=-50dB:d=3,volumedetect','-f','null','-'])
    assert 'silence_duration:' not in check.stderr
    peak=float(re.search(r'max_volume: ([-\d.]+) dB',check.stderr)[1]);assert peak<0
    partial.replace(target)
    subtitle.write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{html.unescape(c["text"])}' for i,c in enumerate(cues))+'\n')
    receipt=dict(id=e['id'],title=e['title'],status='COMPLETE',engine='edge-tts',
                 engine_version=edge_tts.__version__,cast=e['cast'],
                 voice_metadata={k:metadata[a['voice']] for k,a in e['cast'].items()},
                 duration_seconds=duration,word_count=e['word_count'],
                 words_per_minute_including_pauses=round(e['word_count']*60/duration,1),
                 speaker_turns=turns,turn_gap_seconds=GAP,
                 audio_sha256=digest(target.read_bytes()),subtitle_sha256=digest(subtitle.read_bytes()),
                 input_sha256=e['input_sha256'],audio=str(target.relative_to(BASE)),
                 subtitle=str(subtitle.relative_to(BASE)),transcript=f'transcripts/{slug}.md',
                 checks={'full_decode':'passed','distinct_us_voices':True,'subtitle_full_text_match':True,
                         'peak_db':peak,'silence_over_3_seconds':False},human_listening_review='not_performed')
    write_json(receipt_path,receipt)
    joined.unlink()
    print(f'COMPLETE {slug}: {duration:.2f}s',flush=True)


def publish(episodes):
    records=[]
    for e in episodes:
        receipt_path=BASE/'receipts'/f'{e["slug"]}.json'
        if not receipt_path.exists():
            continue
        r=json.loads(receipt_path.read_text())
        assert r['input_sha256']==e['input_sha256']
        e={**e,**{k:r[k] for k in ['audio','subtitle','transcript','duration_seconds','words_per_minute_including_pauses']}}
        role=lambda k:e.get('role_names',{}).get(k,CAST[k]['name'])
        labeled='\n\n'.join(role(p['speaker'])+': '+p['text'] for p in e['segments'])
        text=f'# {e["id"]:02d} · {e["title"]}\n\n{e["title_zh"]}。{e["summary_zh"]}\n\n情境表达：{e["focus"]}。\n\n'
        text+='词语：'+'；'.join(k+' — '+v for k,v in e['words'].items())+'。\n\n'
        text+='常用句：\n\n'+'\n'.join('- '+p for p in e['phrases'])+'\n\n## 分角色英文原文\n\n'
        text+='\n\n'.join('**'+role(p['speaker'])+'**\n\n'+p['text'] for p in e['segments'])+'\n'
        (BASE/e['transcript']).write_text(text)
        e['speech']=labeled
        records.append(e)
    write_json(BASE/'catalog.json',records)
    template=(ROOT/'scripts/templates/little_moments_player.html').read_text()
    (BASE/'播放.html').write_text(template.replace('__EPISODES__',json.dumps(records,ensure_ascii=False).replace('</','<\\/')))
    rows=['# Little Moments · 生活英语 40 集','', '第1集沿用已确认的分角色样音；第2—40集为新故事。','',
          '| 集数 | 场景与原文 | 时长 | 主题 |','|---|---|---|---|']
    for e in records:
        sec=round(e['duration_seconds'])
        rows.append(f'| {e["id"]:02d} | [{e["title_zh"]} · {e["title"]}]({e["transcript"]}) | {sec//60}:{sec%60:02d} | {e["category"]} |')
    (BASE/'目录.md').write_text('\n'.join(rows)+'\n')
    (BASE/'连续播放.m3u8').write_text('#EXTM3U\n'+''.join(f'#EXTINF:{round(e["duration_seconds"])},{e["id"]:02d} {e["title"]}\n{e["audio"]}\n' for e in records))
    print(f'PUBLISHED {len(records)} episodes',flush=True)


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--ids');parser.add_argument('--publish-only',action='store_true');parser.add_argument('--validate-content',action='store_true')
    args=parser.parse_args();episodes=load_episodes()
    if args.validate_content:
        print(json.dumps([(e['id'],e['title'],e['word_count'],len(e['segments'])) for e in episodes],ensure_ascii=False));return
    if not args.publish_only:
        metadata={v['ShortName']:v for v in await edge_tts.list_voices()}
        for a in CAST.values():assert metadata[a['voice']]['Locale']=='en-US'
        write_json(BASE/'voice_metadata.json',{k:metadata[a['voice']] for k,a in CAST.items()})
        wanted=set(int(n) for n in args.ids.split(',')) if args.ids else None
        semaphore=asyncio.Semaphore(3)
        for e in episodes:
            if wanted is None or e['id'] in wanted:
                await build_episode(e,metadata,semaphore)
    publish(episodes)

if __name__=='__main__':asyncio.run(main())
