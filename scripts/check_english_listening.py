#!/usr/bin/env python3
"""Audit the actual 40-episode delivery, not mock audio."""
import concurrent.futures
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path
from build_english_listening import BASE, episodes, narration, settings, stem


def normalized(text):
    return re.sub(r'[^a-z0-9]', '', html.unescape(text).lower())


def check(e):
    name = stem(e)
    receipt = json.loads((BASE / 'receipts' / (name + '.json')).read_text())
    audio = BASE / receipt['audio']
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == receipt['audio_sha256'], name
    voice, rate = settings(e)
    signature = hashlib.sha256((narration(e) + voice + rate).encode()).hexdigest()
    assert signature == receipt['input_sha256'], 'Stale narration: ' + name
    assert voice.startswith('en-US-')
    probe = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(audio)],
        check=True, capture_output=True, text=True).stdout)
    length = float(probe['format']['duration'])
    assert 30 < length < 1200, name
    assert abs(length - receipt['duration_seconds']) < .01
    assert probe['streams'][0]['codec_name'] == 'mp3'
    srt = (BASE / receipt['subtitle']).read_text()
    lines = [line for line in srt.splitlines()
             if line.strip() and not line.strip().isdigit() and '-->' not in line]
    assert normalized(' '.join(lines)) == normalized(narration(e)), 'Subtitle text differs: ' + name
    times = re.findall(r'(\d\d):(\d\d):(\d\d),(\d{3})', srt)
    assert times
    values = [int(h)*3600+int(m)*60+int(s)+int(ms)/1000 for h,m,s,ms in times]
    assert all(a <= b for a, b in zip(values, values[1:])), 'Unordered subtitle: ' + name
    assert 0 <= values[0] and values[-1] <= length+.5
    assert length-values[-1] < 4, 'Possible missing ending: ' + name
    audio_check = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(audio),
         '-af', 'silencedetect=noise=-50dB:d=3,volumedetect', '-f', 'null', '-'],
        check=True, capture_output=True, text=True)
    long_silence = re.findall(r'silence_duration: ([\d.]+)', audio_check.stderr)
    peak = re.search(r'max_volume: ([-\d.]+) dB', audio_check.stderr)
    mean = re.search(r'mean_volume: ([-\d.]+) dB', audio_check.stderr)
    assert not long_silence, 'Unexpected silence over 3s: ' + name
    assert peak and float(peak[1]) < 0, 'Clipping or missing peak: ' + name
    assert mean and -35 < float(mean[1]) < -5, 'Unexpected level: ' + name
    return {'id': e['id'], 'audio': receipt['audio'], 'duration_seconds': length,
            'word_count': receipt['word_count'],
            'words_per_minute': receipt['words_per_minute_including_pauses'],
            'decode': 'passed', 'subtitle_full_text_match': True,
            'subtitle_final_time': values[-1], 'peak_db': float(peak[1]),
            'mean_db': float(mean[1]), 'silence_over_3_seconds': False,
            'sha256': receipt['audio_sha256']}


def main():
    es = episodes()
    assert [e['id'] for e in es] == list(range(1, 41))
    assert len(list((BASE / 'audio').glob('*.mp3'))) == 40
    assert not list((BASE / 'audio').glob('*.partial.mp3'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(check, es))
    total = sum(r['duration_seconds'] for r in checks)
    report = {'episodes': 40, 'all_passed': True, 'total_seconds': total,
              'min_seconds': min(r['duration_seconds'] for r in checks),
              'max_seconds': max(r['duration_seconds'] for r in checks),
              'checks': checks, 'human_listening_review': 'not_performed'}
    (BASE / 'receipts' / 'delivery_audit.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
