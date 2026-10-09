#!/usr/bin/env python3
"""Opt-in live probe -> queued re-probe/download -> full media decode acceptance."""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path
import subprocess
import time

import requests
from PIL import Image, ImageStat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8002')
    parser.add_argument('--link', required=True)
    parser.add_argument('--expected-title', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {'status': 'fail', 'scope': 'live-api-queue-download-full-decode',
              'inputSha256': hashlib.sha256(args.link.encode()).hexdigest()}
    try:
        response = requests.post(args.base_url + '/api/media/probe', json={'link': args.link}, timeout=125)
        response.raise_for_status()
        probe = response.json()
        assert probe.get('success'), probe.get('error')
        assert args.expected_title in probe['title'], probe['title']
        selected = (probe['recommendations'].get('best_compatibility') or probe['recommendations']['best_quality'])['stream']
        report.update(title=probe['title'], streamId=selected['streamId'], selected={
            k: selected.get(k) for k in ('qualityLabel', 'codec', 'width', 'height')})
        response = requests.post(args.base_url + '/api/fetch/batch', json={
            'links': [args.link], 'outputPath': str(args.output_dir.resolve()),
            'outputType': 'mp4', 'videoQuality': selected['streamId'], 'saveAssets': False,
        }, timeout=15)
        response.raise_for_status()
        queued = response.json()
        assert queued.get('success'), queued
        task_id = queued['tasks'][0]['id']
        report['taskId'] = task_id
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            tasks = requests.get(args.base_url + '/api/tasks?kind=media', timeout=10).json()['tasks']
            task = next(t for t in tasks if t['id'] == task_id)
            if task['status'] in ('completed', 'failed', 'cancelled'):
                break
            time.sleep(1)
        assert task['status'] == 'completed', task.get('error') or task['status']
        report['result'] = task['result']
        outputs = list(args.output_dir.glob('*.mp4'))
        assert len(outputs) == 1, outputs
        output = outputs[0]
        info = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(output)
        ], timeout=30))
        assert 'mp4' in info['format']['format_name']
        assert float(info['format']['duration']) > 0
        assert any(s['codec_type'] == 'video' for s in info['streams'])
        assert any(s['codec_type'] == 'audio' for s in info['streams'])
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(output),
                                  '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                                 capture_output=True, text=True, timeout=180)
        assert decoded.returncode == 0, decoded.stderr[-1500:]
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        assert (video['width'], video['height']) == (selected['width'], selected['height'])
        frame_variances = []
        for fraction in (.1, .5, .9):
            frame = subprocess.check_output([
                'ffmpeg', '-v', 'error', '-ss', str(float(info['format']['duration']) * fraction),
                '-i', str(output), '-frames:v', '1', '-vf', 'scale=320:-1', '-f', 'image2pipe', '-c:v', 'png', '-'
            ], timeout=30)
            with Image.open(io.BytesIO(frame)) as image:
                image.load()
                frame_variances.append(ImageStat.Stat(image.convert('RGB')).var)
        assert all(max(v) > 5 for v in frame_variances), frame_variances
        audio = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(output), '-vn',
                                '-af', 'volumedetect', '-f', 'null', '-'],
                               capture_output=True, text=True, timeout=180)
        assert audio.returncode == 0, audio.stderr[-1000:]
        volume = re.search(r'max_volume: ([\d.\-]+) dB', audio.stderr)
        assert volume and float(volume.group(1)) > -60, 'Silent or missing audio signal'
        report.update(status='pass', output=str(output.resolve()), bytes=output.stat().st_size,
                      duration=info['format']['duration'], streams=info['streams'], fullDecode=True,
                      frameVariances=frame_variances, audioMaxVolumeDb=float(volume.group(1)))
        print('LIVE_STREAM_SELECTION=passed', task_id, output)
    except Exception as exc:
        report['error'] = str(exc)[:2000]
        raise
    finally:
        (args.output_dir / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
