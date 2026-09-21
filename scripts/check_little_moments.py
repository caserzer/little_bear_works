#!/usr/bin/env python3
"""Validate real MP3s, role assignments, complete subtitles and delivery metadata."""
import concurrent.futures
import hashlib
import json
import re
from build_little_moments import BASE, CAST, SAMPLE, digest, load_episodes, normalize, run


def check(e):
    r=json.loads((BASE/'receipts'/f'{e["slug"]}.json').read_text())
    assert r['status']=='COMPLETE'
    assert r['input_sha256']==e['input_sha256']
    audio=BASE/r['audio'];srt=BASE/r['subtitle']
    assert digest(audio.read_bytes())==r['audio_sha256']
    if e.get('approved_sample'):
        assert audio.read_bytes()==(SAMPLE/'sample_v3_cast.mp3').read_bytes()
        assert srt.read_bytes()==(SAMPLE/'sample_v3_cast.srt').read_bytes()
    else:
        assert digest(srt.read_bytes())==r['subtitle_sha256']
    assert len(r['speaker_turns'])==len(e['segments'])
    voices=set()
    last=0
    for part,turn in zip(e['segments'],r['speaker_turns']):
        actor=CAST[part['speaker']]
        assert turn['speaker']==part['speaker']
        assert turn['voice']==actor['voice']
        assert r['cast'][part['speaker']]['rate']==actor['rate']
        assert r['cast'][part['speaker']]['pitch']==actor['pitch']
        assert r['voice_metadata'][part['speaker']]['Locale']=='en-US'
        assert 0<=last<=turn['start']<turn['end']
        last=turn['end'];voices.add(turn['voice'])
    assert len(voices)==len(e['cast'])>=2
    probe=json.loads(run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(audio)]).stdout)
    length=float(probe['format']['duration'])
    assert 30<length<1200 and abs(length-r['duration_seconds'])<.01
    assert probe['streams'][0]['codec_name']=='mp3'
    assert probe['streams'][0]['sample_rate']=='24000'
    assert 0<=length-last<.2
    text=srt.read_text()
    cue_text=' '.join(l for l in text.splitlines() if l.strip() and not l.isdigit() and '-->' not in l)
    assert normalize(cue_text)==normalize(e['speech']),e['slug']
    times=re.findall(r'(\d\d):(\d\d):(\d\d),(\d{3})',text)
    vals=[int(h)*3600+int(m)*60+int(s)+int(ms)/1000 for h,m,s,ms in times]
    assert vals and all(a<=b for a,b in zip(vals,vals[1:]))
    assert 0<=vals[0]<vals[-1]<=length and length-vals[-1]<1
    transcript=(BASE/r['transcript']).read_text()
    assert all(p['text'] in transcript for p in e['segments'])
    sound=run(['ffmpeg','-hide_banner','-nostats','-i',str(audio),'-af',
               'silencedetect=noise=-50dB:d=3,volumedetect','-f','null','-']).stderr
    assert 'silence_duration:' not in sound
    peak=float(re.search(r'max_volume: ([-\d.]+) dB',sound)[1])
    mean=float(re.search(r'mean_volume: ([-\d.]+) dB',sound)[1])
    assert peak<0 and -35<mean<-5
    return dict(id=e['id'],audio=r['audio'],duration_seconds=length,word_count=e['word_count'],
                words_per_minute=r['words_per_minute_including_pauses'],distinct_voices=len(voices),
                decode='passed',subtitle_full_text_match=True,peak_db=peak,mean_db=mean,
                silence_over_3_seconds=False,audio_sha256=r['audio_sha256'])


def main():
    episodes=load_episodes()
    assert [e['id'] for e in episodes]==list(range(1,41))
    assert len(list((BASE/'audio').glob('*.mp3')))==40
    assert len(list((BASE/'subtitles').glob('*.srt')))==40
    assert len(list((BASE/'transcripts').glob('*.md')))==40
    assert len({e['title'] for e in episodes})==40
    catalog=json.loads((BASE/'catalog.json').read_text())
    assert [e['id'] for e in catalog]==list(range(1,41))
    for a,b in zip(episodes,catalog):
        assert a['input_sha256']==b['input_sha256']
        assert a['segments']==b['segments']
    assert '__EPISODES__' not in (BASE/'播放.html').read_text()
    playlist=(BASE/'连续播放.m3u8').read_text().splitlines()
    assert [x for x in playlist if x.startswith('audio/')]==[e['audio'] for e in catalog]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        checks=list(pool.map(check,episodes))
    report=dict(episodes=40,all_passed=True,total_seconds=sum(c['duration_seconds'] for c in checks),
                min_seconds=min(c['duration_seconds'] for c in checks),max_seconds=max(c['duration_seconds'] for c in checks),
                total_words=sum(c['word_count'] for c in checks),approved_sample_byte_identical=True,
                checks=checks,human_listening_review='Episode 1 approved by user; episodes 2-40 technically validated, no human listening claimed.')
    (BASE/'receipts/delivery_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
