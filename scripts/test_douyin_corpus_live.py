#!/usr/bin/env python3
"""Opt-in real App-copied corpus: 20 single tasks then one 10-item batch.
Stores every original failure; reruns must use a fresh attempt directory.
"""
import argparse
import io
import json
import re
import subprocess
import time
from pathlib import Path
import requests
from PIL import Image, ImageStat
from subtitles.service import parse_subtitles
from subtitles.chinese import to_simplified

BASE = 'http://127.0.0.1:8002'

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def tasks():
    r = requests.get(BASE + '/api/tasks?kind=media', timeout=15)
    r.raise_for_status()
    return {t['id']: t for t in r.json()['tasks']}

def terminal(task_id, timeout=1200, subtitles=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = tasks()[task_id]
        if t['status'] in ('failed', 'cancelled'):
            return t
        if t['status'] == 'completed':
            job = (t.get('result') or {}).get('subtitleJob') or {}
            if not subtitles or job.get('status') not in ('pending', 'running'):
                return t
        time.sleep(3)
    raise TimeoutError(f'Task {task_id} did not finish within {timeout}s')

def command(args, timeout=1200):
    r = subprocess.run(args, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors='replace')[-2000:])
    return r

def validate(t, folder, cached=None):
    result = t['result']
    if cached:
        media_checks = cached
        duration = cached['duration']
    else:
        video = Path(result['outputPath'])
        info = json.loads(command(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)], 30).stdout)
        duration = float(info['format']['duration'])
        assert 'mp4' in info['format']['format_name'] and duration > 0
        assert any(s['codec_type'] == 'video' for s in info['streams'])
        assert any(s['codec_type'] == 'audio' for s in info['streams'])
        command(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
        variances = []
        for n, fraction in enumerate((.1, .5, .9)):
            data = command(['ffmpeg', '-v', 'error', '-ss', str(duration * fraction), '-i', str(video), '-frames:v', '1', '-vf', 'scale=480:-1', '-f', 'image2pipe', '-c:v', 'png', '-'], 60).stdout
            (folder / f'frame-{n}.png').write_bytes(data)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                variances.append(ImageStat.Stat(image.convert('RGB')).var)
        assert all(max(v) > 5 for v in variances), 'Blank frame sample'
        audio = command(['ffmpeg', '-hide_banner', '-i', str(video), '-vn', '-af', 'volumedetect', '-f', 'null', '-']).stderr.decode(errors='replace')
        volume = re.search(r'max_volume: ([\d.\-]+) dB', audio)
        assert volume and float(volume.group(1)) > -60, 'Silent audio'
        cover = Path(result['assets'].get('cover') or '')
        assert cover.is_file(), 'Cover missing'
        with Image.open(cover) as image:
            image.load()
            cover_info = {'format': image.format, 'size': image.size, 'variance': ImageStat.Stat(image.convert('RGB')).var}
            assert max(cover_info['variance']) > 5, 'Blank cover'
        media_checks = {'video': str(video), 'bytes': video.stat().st_size, 'duration': duration, 'streams': info['streams'], 'fullDecode': True, 'frameVariances': variances, 'audioMaxVolumeDb': float(volume.group(1)), 'cover': cover_info}
    subs = result['assets'].get('subtitles') or []
    subtitle_checks = []
    for sub in subs:
        path = Path(sub)
        text = path.read_text(encoding='utf-8', errors='strict')
        assert text.strip(), 'Empty subtitle file'
        assert '\ufffd' not in text, 'Damaged subtitle text contains U+FFFD'
        doc = parse_subtitles(text, filename=path.name)
        assert doc.cues, 'No parsed cues'
        for cue in doc.cues:
            assert 0 <= cue.start < cue.end <= duration + 2, 'Cue outside media timeline'
            assert cue.text.strip(), 'Empty cue'
        subtitle_checks.append({'path': str(path), 'cues': len(doc.cues), 'sample': [c.text for c in doc.cues[:10]], 'simplified': to_simplified(text) == text})
        assert to_simplified(text) == text, 'Traditional Chinese output'
    sources = [x.get('source') for x in result['assets'].get('subtitleDetails') or []]
    return {**media_checks, 'subtitles': subtitle_checks, 'subtitleSources': sources, 'subtitleJob': result.get('subtitleJob'), 'subtitleContentReview': 'pending listening/visual comparison', 'fileChecksPass': bool(subtitle_checks) and 'metadata-text' not in sources}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--attempt', default='attempt-1')
    parser.add_argument('--start', type=int, default=1, choices=range(1, 21))
    parser.add_argument('--finalize-only', action='store_true', help='Read back existing real outputs; never enqueue duplicate downloads')
    parser.add_argument('--wait-seconds', type=int, default=1200)
    args = parser.parse_args()
    root = args.corpus.resolve()
    attempt = root / args.attempt
    if args.finalize_only:
        records = json.loads((attempt / 'results.json').read_text())
        manifest = json.loads((attempt / 'manifest.json').read_text())
        batch_queue = json.loads((attempt / 'batch-queue.json').read_text())
        by_case = {r['case']: r for r in records}
        for case, task in zip(manifest[20:], batch_queue['tasks']):
            by_case.setdefault(case['case'], {**case, 'taskId': task['id']})
        deadline = time.monotonic() + args.wait_seconds
        pending = set(by_case)
        while pending:
            current = tasks()
            for number in list(pending):
                record = by_case[number]
                t = current[record['taskId']]
                job = (t.get('result') or {}).get('subtitleJob') or {}
                if t['status'] in ('pending', 'running') or job.get('status') in ('pending', 'running'):
                    if time.monotonic() < deadline:
                        continue
                    record['status'] = 'unfinished'
                elif t['status'] != 'completed':
                    record['status'] = 'media-failed'
                    record['error'] = t.get('error')
                else:
                    folder = attempt / f'case-{number:03}'
                    try:
                        record['checks'] = validate(t, folder, cached=record.get('checks'))
                        record['status'] = 'file-pass-content-review-pending' if record['checks']['fileChecksPass'] else 'subtitle-missing-or-metadata-only'
                    except Exception as exc:
                        record['status'] = 'subtitle-file-fail'
                        record['error'] = str(exc)
                save(attempt / f'case-{number:03}' / 'task-final.json', t)
                pending.remove(number)
                print('READBACK', number, record['status'], record.get('error', ''), flush=True)
            save(attempt / 'final-results.json', [by_case[n] for n in sorted(by_case)])
            if pending:
                time.sleep(5)
        return
    attempt.mkdir(exist_ok=False)
    cases = []
    for n in range(1, 31):
        share = (root / f'share-{n:03}.txt').read_text()
        link = re.search(r'https://v.douyin.com/[^\s]+', share).group()
        cases.append({'case': n, 'shareText': share, 'link': link, 'mode': 'single' if n <= 20 else 'batch'})
    assert len({c['link'] for c in cases}) == 30
    save(attempt / 'manifest.json', cases)
    results = []
    def probe(c):
        folder = attempt / f"case-{c['case']:03}"
        folder.mkdir(exist_ok=True)
        started = time.monotonic()
        r = requests.post(BASE + '/api/media/probe', json={'link': c['shareText']}, timeout=125)
        body = r.json()
        save(folder / 'probe.json', {'httpStatus': r.status_code, 'elapsedSeconds': time.monotonic()-started, 'body': body})
        if not body.get('success'):
            raise RuntimeError(body.get('error') or str(body))
        c['probeTitle'] = body.get('title')
        return folder
    def check(c, task_id):
        folder = attempt / f"case-{c['case']:03}"
        record = {**c, 'taskId': task_id, 'status': 'fail'}
        try:
            t = terminal(task_id, subtitles=False)
            save(folder / 'task.json', t)
            assert t['status'] == 'completed', t.get('error') or t['status']
            record['checks'] = validate(t, folder)
            record['status'] = 'video-pass-subtitle-review-pending'
        except Exception as exc:
            record['error'] = str(exc)
        results.append(record)
        save(attempt / 'results.json', results)
        print(c['case'], record['status'], record.get('error', ''), flush=True)
    for c in cases[args.start - 1:20]:
        try:
            folder = probe(c)
            r = requests.post(BASE + '/api/fetch/batch', json={'links': [c['shareText']], 'outputPath': str(folder), 'outputType': 'mp4', 'saveAssets': True}, timeout=20)
            q = r.json()
            save(folder / 'queue.json', q)
            assert q.get('success'), q
            check(c, q['tasks'][0]['id'])
        except Exception as exc:
            results.append({**c, 'status': 'probe-or-queue-fail', 'error': str(exc)})
            save(attempt / 'results.json', results)
            print(c['case'], 'probe-or-queue-fail', str(exc), flush=True)
        if results[-1]['status'] != 'video-pass-subtitle-review-pending':
            raise RuntimeError(f"Stopped at case {c['case']}: inspect and repair before continuing")
    batch = cases[20:]
    for c in batch:
        try:
            probe(c)
        except Exception as exc:
            c['probeError'] = str(exc)
    r = requests.post(BASE + '/api/fetch/batch', json={'links': [c['shareText'] for c in batch], 'outputPath': str(attempt / 'batch-output'), 'outputType': 'mp4', 'saveAssets': True}, timeout=20)
    q = r.json()
    save(attempt / 'batch-queue.json', q)
    assert q.get('success') and len(q['tasks']) == 10, q
    for c, task in zip(batch, q['tasks']):
        assert re.search(r'https://v.douyin.com/[^\s]+', task['payload']['link']).group() == c['link']
        check(c, task['id'])
        if results[-1]['status'] != 'video-pass-subtitle-review-pending':
            raise RuntimeError(f"Stopped at batch case {c['case']}: remaining queued jobs are preserved")
    for record in results:
        folder = attempt / f"case-{record['case']:03}"
        try:
            t = terminal(record['taskId'], timeout=3600, subtitles=True)
            save(folder / 'task-final.json', t)
            record['checks'] = validate(t, folder, cached=record['checks'])
            record['status'] = 'file-pass-content-review-pending' if record['checks']['fileChecksPass'] else 'subtitle-missing-or-metadata-only'
        except Exception as exc:
            record['status'] = 'subtitle-file-fail'
            record['error'] = str(exc)
        save(attempt / 'results.json', results)
        print('SUBTITLE', record['case'], record['status'], record.get('error', ''), flush=True)
    print('Completed real file checks; semantic content review is separate.', flush=True)

if __name__ == '__main__':
    main()
