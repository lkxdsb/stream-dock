#!/usr/bin/env python3
"""生成多类型样例文件，并对 StreamDock 本地文件转换做鲁棒性/准确性验收。

默认在 /tmp 下创建隔离工作区，生成 fixture、执行转换、做内容级断言，并写出 JSON 报告。
用法：
  python scripts/test_conversion_robustness.py
  python scripts/test_conversion_robustness.py --keep --workdir /tmp/streamdock-convert-lab
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converters.pipeline import convert_file  # noqa: E402
from runtime_checks import augmented_path, resolve_tool_path, validate_media_output  # noqa: E402

os.environ['PATH'] = augmented_path()
RELEASE_CONTRACT = ROOT / 'scripts' / 'conversion_release_contract.json'


@dataclass
class Case:
    name: str
    source: str
    target: str
    input_path: Path
    validate: Callable[[Path], None]
    expected_error: str | None = None
    notes: str = ''
    media_options: dict[str, Any] = field(default_factory=dict)
    archive_options: dict[str, Any] = field(default_factory=dict)
    image_quality: int | None = None


@dataclass
class CaseResult:
    name: str
    source: str
    target: str
    status: str
    elapsed_seconds: float
    output_path: str | None = None
    error: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    notes: str = ''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def generate_fixtures(root: Path) -> dict[str, Path]:
    fixtures = root / 'fixtures'
    fixtures.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    seven_zip_fixture = ROOT / 'tests' / 'fixtures' / 'real' / 'archive.7z'
    if seven_zip_fixture.exists() and shutil.which('bsdtar', path=augmented_path()):
        paths['7z'] = fixtures / 'archive.7z'
        shutil.copy2(seven_zip_fixture, paths['7z'])
    rar_fixture = ROOT / 'tests' / 'fixtures' / 'real' / 'archive.rar'
    if rar_fixture.exists() and shutil.which('bsdtar', path=augmented_path()):
        paths['rar'] = fixtures / 'archive.rar'
        shutil.copy2(rar_fixture, paths['rar'])
    split_parts = sorted((ROOT / 'tests' / 'fixtures' / 'real').glob('rar5-vols.part*.rar'))
    if len(split_parts) == 3:
        split_root = fixtures / 'split-rar'; split_root.mkdir()
        for part in split_parts:
            shutil.copy2(part, split_root / part.name)
        paths['rar_split'] = split_root / split_parts[0].name

    rows = [
        {'id': '1', 'name': '张三', 'score': '98.5', 'remark': '含逗号, 引号"与 emoji ✅'},
        {'id': '2', 'name': '李四', 'score': '87', 'remark': '第二行中文内容'},
        {'id': '3', 'name': 'Ada', 'score': '100', 'remark': 'ASCII fallback'},
    ]
    paths['csv'] = fixtures / 'table_utf8.csv'
    with paths['csv'].open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'name', 'score', 'remark'])
        writer.writeheader(); writer.writerows(rows)

    paths['tsv'] = fixtures / 'table_utf8.tsv'
    with paths['tsv'].open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'name', 'score', 'remark'], delimiter='\t')
        writer.writeheader(); writer.writerows(rows)

    paths['json'] = fixtures / 'rows.json'
    paths['json'].write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')

    paths['ndjson'] = fixtures / 'rows.ndjson'
    paths['ndjson'].write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')

    paths['yaml'] = fixtures / 'config.yaml'
    paths['yaml'].write_text('title: 鲁棒性测试\nitems:\n  - name: 张三\n    ok: true\n', encoding='utf-8')

    paths['toml'] = fixtures / 'config.toml'
    paths['toml'].write_text('[project]\nname = "StreamDock"\nowner = "张三"\ncount = 3\n', encoding='utf-8')

    paths['xml'] = fixtures / 'items.xml'
    paths['xml'].write_text('<?xml version="1.0" encoding="utf-8"?><root><item><name>张三</name><score>98</score></item></root>', encoding='utf-8')

    try:
        import openpyxl  # type: ignore
        from openpyxl.chart import BarChart, Reference  # type: ignore
        from openpyxl.styles import Font, PatternFill  # type: ignore
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = '数据'
        ws.append(['id', 'name', 'score', 'remark'])
        for row in rows:
            ws.append([row['id'], row['name'], float(row['score']), row['remark']])
        paths['xlsx'] = fixtures / 'table.xlsx'
        wb.save(paths['xlsx'])

        office = openpyxl.Workbook(); sheet = office.active; sheet.title = '中文数据'
        sheet.append(['姓名', '分数', '公式']); sheet.append(['张三', 98, '=B2+2']); sheet.append(['李四', 87, '=B3+3'])
        sheet['A1'].font = Font(bold=True, color='FFFFFF'); sheet['A1'].fill = PatternFill('solid', fgColor='336699')
        sheet.merge_cells('A5:C5'); sheet['A5'] = '合并标题'; sheet.row_dimensions[3].hidden = True; sheet.column_dimensions['C'].hidden = True
        chart = BarChart(); chart.title = '分数图'; chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True); sheet.add_chart(chart, 'E2')
        office.create_sheet('emoji 😀').append(['RTL', 'مرحبا'])
        office_seed = fixtures / 'office-complex.xlsx'; office.save(office_seed)
        soffice = shutil.which('soffice', path=augmented_path())
        if soffice:
            legacy_dir = fixtures / 'legacy-office'; legacy_dir.mkdir()
            for extension in ('ods', 'xls'):
                subprocess.run([soffice, '--headless', '--convert-to', extension, '--outdir', str(legacy_dir), str(office_seed)], check=True, capture_output=True, text=True)
                produced = legacy_dir / f'office-complex.{extension}'
                if produced.exists():
                    paths[extension] = produced
    except Exception:
        pass

    try:
        from docx import Document  # type: ignore
        from PIL import Image  # type: ignore
        rich_image = fixtures / 'docx-image.png'
        Image.new('RGB', (37, 19), (12, 120, 220)).save(rich_image)
        document = Document()
        document.sections[0].header.paragraphs[0].text = '页眉中文'
        document.add_heading('真实 Office 文档', level=1)
        paragraph = document.add_paragraph('正文 emoji 😀 ')
        document.add_comment(paragraph.runs[0], text='请复核这段内容', author='审阅人', initials='QA')
        paragraph.add_run().add_picture(str(rich_image))
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = '姓名'; table.cell(0, 1).text = '分数'
        table.cell(1, 0).text = '张三'; table.cell(1, 1).text = '98'
        document.sections[0].footer.paragraphs[0].text = '页脚内容'
        paths['docx_rich'] = fixtures / 'rich.docx'
        document.save(paths['docx_rich'])
    except Exception:
        pass

    paths['md'] = fixtures / 'readme.md'
    paths['md'].write_text(textwrap.dedent('''\
        # StreamDock 转换测试

        这是一段中文 Markdown，包含 **加粗**、列表和表格。

        | 姓名 | 分数 |
        | --- | ---: |
        | 张三 | 98 |
        | Ada | 100 |
        '''), encoding='utf-8')

    paths['html'] = fixtures / 'page.html'
    paths['html'].write_text('<!doctype html><meta charset="utf-8"><h1>标题</h1><p>中文段落 ✅</p>', encoding='utf-8')

    paths['txt'] = fixtures / 'plain.txt'
    paths['txt'].write_text('第一行中文\nSecond line ✅\n第三行\n', encoding='utf-8')

    paths['rtf'] = fixtures / 'sample.rtf'
    paths['rtf'].write_text(r'{\rtf1\ansi StreamDock \par plain text paragraph}', encoding='utf-8')

    paths['srt'] = fixtures / 'caption.srt'
    paths['srt'].write_text('1\n00:00:00,000 --> 00:00:01,500\n你好 StreamDock\n\n2\n00:00:01,500 --> 00:00:03,000\n第二句字幕\n', encoding='utf-8')
    paths['vtt'] = fixtures / 'caption.vtt'
    paths['vtt'].write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n你好 VTT\n', encoding='utf-8')
    paths['lrc'] = fixtures / 'lyric.lrc'
    paths['lrc'].write_text('[00:00.00]第一句歌词\n[00:02.50]第二句歌词\n', encoding='utf-8')
    paths['ass'] = fixtures / 'caption.ass'
    paths['ass'].write_text('[Events]\nDialogue: 0,0:00:00.00,0:00:01.20,Default,,0,0,0,,你好\\NASS\n', encoding='utf-8')

    try:
        from PIL import Image, ImageDraw  # type: ignore
        img = Image.new('RGBA', (160, 90), (30, 80, 160, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 10, 150, 80), fill=(255, 220, 60, 210))
        draw.ellipse((55, 20, 105, 70), fill=(230, 50, 80, 230))
        paths['png'] = fixtures / 'cover.png'; img.save(paths['png'])
        img.convert('RGB').save(fixtures / 'cover.jpg'); paths['jpg'] = fixtures / 'cover.jpg'
        frames = []
        for idx, color in enumerate(((255, 0, 0), (0, 180, 80), (60, 80, 255))):
            frame = Image.new('RGB', (64, 64), color)
            ImageDraw.Draw(frame).text((8, 24), str(idx + 1), fill=(255, 255, 255))
            frames.append(frame)
        paths['gif'] = fixtures / 'anim.gif'
        frames[0].save(paths['gif'], save_all=True, append_images=frames[1:], duration=80, loop=0)
        paths['apng'] = fixtures / 'anim.png'
        rgba_frames = [frame.convert('RGBA') for frame in frames]
        rgba_frames[0].save(paths['apng'], save_all=True, append_images=rgba_frames[1:], duration=[80, 90, 100], loop=0)
        paths['tiff_multi'] = fixtures / 'multipage.tiff'
        frames[0].save(paths['tiff_multi'], save_all=True, append_images=frames[1:])
    except Exception:
        pass

    archive_src = fixtures / 'folder_src'
    (archive_src / 'nested').mkdir(parents=True, exist_ok=True)
    (archive_src / 'nested' / '中文.txt').write_text('archive ok ✅', encoding='utf-8')
    (archive_src / 'numbers.csv').write_text('n\n1\n2\n', encoding='utf-8')
    (archive_src / 'nested' / '中文.txt').chmod(0o640); (archive_src / 'nested').chmod(0o750)
    os.utime(archive_src / 'nested' / '中文.txt', (1600000000, 1600000000)); os.utime(archive_src / 'nested', (1600000000, 1600000000))
    paths['folder'] = archive_src
    paths['zip'] = fixtures / 'sample.zip'
    with zipfile.ZipFile(paths['zip'], 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in archive_src.rglob('*'):
            zf.write(p, p.relative_to(archive_src))
    paths['tar.gz'] = fixtures / 'sample.tar.gz'
    with tarfile.open(paths['tar.gz'], 'w:gz') as tf:
        tf.add(archive_src, arcname='folder_src')
    paths['gz'] = fixtures / 'plain.txt.gz'
    with gzip.open(paths['gz'], 'wb') as f:
        f.write(paths['txt'].read_bytes())
    paths['unsafe_zip'] = fixtures / 'unsafe.zip'
    with zipfile.ZipFile(paths['unsafe_zip'], 'w') as zf:
        zf.writestr('../escape.txt', 'blocked')
    zip_command = shutil.which('zip', path=augmented_path())
    if zip_command:
        encrypted_source = fixtures / 'encrypted-source'; encrypted_source.mkdir()
        (encrypted_source / 'secret.txt').write_text('机密中文 😀\n', encoding='utf-8')
        paths['encrypted_zip'] = fixtures / 'encrypted.zip'
        subprocess.run([zip_command, '-q', '-P', 's3cret!', str(paths['encrypted_zip']), 'secret.txt'], cwd=encrypted_source, check=True)

    ffmpeg = resolve_tool_path('ffmpeg')
    if shutil.which('ffmpeg', path=augmented_path()):
        # A self-contained, standards-valid AMR-NB file.  FT=7/Q=1 frames are
        # decodable by FFmpeg even when this build has no AMR encoder.
        paths['amr'] = fixtures / 'speech.amr'
        paths['amr'].write_bytes(b'#!AMR\n' + (bytes([0x3C]) + b'\0' * 31) * 50)
        paths['wav'] = fixtures / 'tone.wav'
        subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=0.7', str(paths['wav'])], check=True, env={**os.environ, 'PATH': augmented_path()})
        paths['mp4'] = fixtures / 'sample.mp4'
        subprocess.run([
            ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10:duration=1',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(paths['mp4'])
        ], check=True, env={**os.environ, 'PATH': augmented_path()})
        if 'h264_videotoolbox' in subprocess.run([ffmpeg, '-hide_banner', '-encoders'], text=True, capture_output=True, env={**os.environ, 'PATH': augmented_path()}).stdout:
            paths['mov_hardware'] = fixtures / 'hardware.mov'
            subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(paths['mp4']), '-c', 'copy', str(paths['mov_hardware'])], check=True, env={**os.environ, 'PATH': augmented_path()})

        # A container-level fidelity fixture: Unicode metadata, chapter and
        # embedded subtitle must survive MKV -> MP4, not merely decode.
        subtitle = fixtures / 'embedded.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:00,800\n内嵌字幕 😀\n', encoding='utf-8')
        subtitle_second = fixtures / 'embedded-en.srt'
        subtitle_second.write_text('1\n00:00:00,000 --> 00:00:00,800\nSecond subtitle\n', encoding='utf-8')
        ffmeta = fixtures / 'chapters.ffmeta'
        ffmeta.write_text(';FFMETADATA1\ntitle=StreamDock 真实媒体\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=900\ntitle=第一章\n', encoding='utf-8')
        paths['mkv_complex'] = fixtures / 'complex.mkv'
        subprocess.run([
            ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24:duration=1',
            '-f', 'lavfi', '-i', 'sine=frequency=523:sample_rate=44100:duration=1',
            '-f', 'lavfi', '-i', 'sine=frequency=659:sample_rate=44100:duration=1',
            '-i', str(subtitle), '-i', str(subtitle_second), '-i', str(ffmeta),
            '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s', '-map', '4:s',
            '-map_metadata', '5', '-map_chapters', '5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-c:s', 'srt', str(paths['mkv_complex']),
        ], check=True, env={**os.environ, 'PATH': augmented_path()})

        if 'jpg' in paths:
            base_m4a = fixtures / 'base.m4a'
            paths['m4a_cover'] = fixtures / 'covered.m4a'
            subprocess.run([
                ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:sample_rate=44100:duration=1', '-c:a', 'aac',
                '-metadata', 'title=中文音频 😀', str(base_m4a),
            ], check=True, env={**os.environ, 'PATH': augmented_path()})
            subprocess.run([
                ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(base_m4a),
                '-i', str(paths['jpg']), '-map', '0:a', '-map', '1:v', '-c', 'copy',
                '-disposition:v', 'attached_pic', '-metadata', 'title=中文音频 😀',
                str(paths['m4a_cover']),
            ], check=True, env={**os.environ, 'PATH': augmented_path()})

    return paths


def build_cases(paths: dict[str, Path]) -> list[Case]:
    cases: list[Case] = []

    def has(*keys: str) -> bool:
        return all(key in paths for key in keys)

    if has('csv'):
        cases.append(Case('CSV 保留中文/emoji到 JSON', 'csv', 'json', paths['csv'], lambda p: require(any(row.get('name') == '张三' and 'emoji' in row.get('remark', '') for row in read_json(p)), 'CSV→JSON 内容丢失')))
        cases.append(Case('CSV 到 XLSX 表格行数', 'csv', 'xlsx', paths['csv'], validate_xlsx_contains_zhangsan))
    if has('xlsx'):
        cases.append(Case('XLSX 到 CSV 内容回读', 'xlsx', 'csv', paths['xlsx'], validate_csv_contains_zhangsan))
    if has('ods'):
        cases.append(Case('ODS 到 XLSX 保留多表/公式/样式/图表', 'ods', 'xlsx', paths['ods'], lambda p: validate_complex_workbook(p, require_chart=True)))
    if has('xls'):
        cases.append(Case('XLS 到 XLSX 保留多表/公式/样式', 'xls', 'xlsx', paths['xls'], lambda p: validate_complex_workbook(p, require_chart=False)))
    if has('json'):
        cases.append(Case('JSON 到 CSV 字段展开', 'json', 'csv', paths['json'], validate_csv_contains_zhangsan))
        cases.append(Case('JSON 到 YAML Unicode', 'json', 'yaml', paths['json'], lambda p: require('张三' in p.read_text(encoding='utf-8'), 'JSON→YAML 中文丢失')))
    if has('ndjson'):
        cases.append(Case('NDJSON 到 CSV 多行', 'ndjson', 'csv', paths['ndjson'], validate_csv_contains_zhangsan))
    if has('yaml'):
        cases.append(Case('YAML 到 JSON 嵌套结构', 'yaml', 'json', paths['yaml'], lambda p: require(read_json(p)['items'][0]['name'] == '张三', 'YAML→JSON 嵌套值错误')))
    if has('toml'):
        cases.append(Case('TOML 到 JSON 嵌套结构', 'toml', 'json', paths['toml'], lambda p: require(read_json(p)['project']['owner'] == '张三', 'TOML→JSON 值错误')))
    if has('xml'):
        cases.append(Case('XML 到 JSON 标签结构', 'xml', 'json', paths['xml'], lambda p: require(read_json(p)['root']['item']['name'] == '张三', 'XML→JSON 标签值错误')))

    if has('md'):
        cases.append(Case('Markdown 到 HTML 表格/中文', 'md', 'html', paths['md'], lambda p: require('<table>' in p.read_text(encoding='utf-8') and '张三' in p.read_text(encoding='utf-8'), 'MD→HTML 表格或中文缺失')))
        cases.append(Case('Markdown 到 PDF 非空', 'md', 'pdf', paths['md'], lambda p: require(p.stat().st_size > 1000, 'MD→PDF 文件过小')))
        cases.append(Case('Markdown 到 DOCX 段落', 'md', 'docx', paths['md'], validate_docx_contains_streamdock))
    if has('html'):
        cases.append(Case('HTML 到 TXT 去标签', 'html', 'txt', paths['html'], lambda p: require('中文段落' in p.read_text(encoding='utf-8') and '<p>' not in p.read_text(encoding='utf-8'), 'HTML→TXT 去标签失败')))
    if has('txt'):
        cases.append(Case('TXT 到 RTF 基础文本', 'txt', 'rtf', paths['txt'], lambda p: require(r'\rtf1' in p.read_text(encoding='utf-8'), 'TXT→RTF 头缺失')))
    if has('rtf'):
        cases.append(Case('RTF 到 TXT 文本抽取', 'rtf', 'txt', paths['rtf'], lambda p: require('StreamDock' in p.read_text(encoding='utf-8'), 'RTF→TXT 文本缺失')))
    if has('docx_rich'):
        cases.append(Case('DOCX 到 HTML 保留页眉页脚/表格/图片', 'docx', 'html', paths['docx_rich'], validate_rich_docx_html))

    if has('png'):
        cases.append(Case('PNG 到 JPG 尺寸/模式', 'png', 'jpg', paths['png'], lambda p: validate_image(p, (160, 90))))
        cases.append(Case('PNG 到 WEBP 尺寸/格式', 'png', 'webp', paths['png'], lambda p: validate_image(p, (160, 90))))
        cases.append(Case('PNG 到 ICO 非空', 'png', 'ico', paths['png'], lambda p: require(p.stat().st_size > 100, 'PNG→ICO 文件过小')))
        cases.append(Case('PNG 到 JPEG 低质量参数', 'png', 'jpg', paths['png'], lambda p: validate_image(p, (160, 90)), image_quality=20))
        cases.append(Case('PNG 到 JPEG 高质量参数', 'png', 'jpg', paths['png'], lambda p: validate_image(p, (160, 90)), image_quality=95))
    if has('gif'):
        cases.append(Case('GIF 到 PNG 帧目录', 'gif', 'png', paths['gif'], validate_gif_frames))
    if has('apng'):
        cases.append(Case('APNG 到 GIF 保留全部帧', 'png', 'gif', paths['apng'], lambda p: validate_animated_image(p, 3)))
    if has('tiff_multi'):
        cases.append(Case('多帧 TIFF 到 APNG 保留全部帧', 'tiff', 'png', paths['tiff_multi'], lambda p: validate_animated_image(p, 3)))
        cases.append(Case('多帧 TIFF 到 JPEG 拒绝静默丢帧', 'tiff', 'jpg', paths['tiff_multi'], lambda p: None, expected_error='无法完整保留所有帧'))

    if has('srt'):
        cases.append(Case('SRT 到 VTT 时间格式', 'srt', 'vtt', paths['srt'], lambda p: require(p.read_text(encoding='utf-8').startswith('WEBVTT') and '00:00:00.000' in p.read_text(encoding='utf-8'), 'SRT→VTT 格式错误')))
    if has('vtt'):
        cases.append(Case('VTT 到 SRT 时间格式', 'vtt', 'srt', paths['vtt'], lambda p: require('00:00:00,000' in p.read_text(encoding='utf-8'), 'VTT→SRT 时间格式错误')))
    if has('lrc'):
        cases.append(Case('LRC 到 SRT 歌词时间轴', 'lrc', 'srt', paths['lrc'], lambda p: require('第一句歌词' in p.read_text(encoding='utf-8') and '00:00:02,500' in p.read_text(encoding='utf-8'), 'LRC→SRT 内容错误')))
    if has('ass'):
        cases.append(Case('ASS 到 SRT 换行降级', 'ass', 'srt', paths['ass'], lambda p: require('你好\nASS' in p.read_text(encoding='utf-8'), 'ASS→SRT 换行/文本错误')))

    if has('folder'):
        cases.append(Case('文件夹到 ZIP 目录结构', 'folder', 'zip', paths['folder'], validate_zip_contains_nested))
        cases.append(Case('文件夹到 TAR.GZ 目录结构', 'folder', 'tar.gz', paths['folder'], lambda p: require(tarfile.is_tarfile(p), 'folder→tar.gz 不是有效 tar')))
    if has('zip'):
        cases.append(Case('ZIP 到文件夹安全解压/属性保留', 'zip', 'folder', paths['zip'], validate_zip_extraction_metadata))
    if has('tar.gz'):
        cases.append(Case('TAR.GZ 到 ZIP 重打包', 'tar.gz', 'zip', paths['tar.gz'], lambda p: require(zipfile.is_zipfile(p), 'tar.gz→zip 不是有效 zip')))
    if has('gz'):
        cases.append(Case('GZ 单文件解压', 'gz', 'folder', paths['gz'], lambda p: require((p / 'plain.txt').exists(), 'GZ→folder 解压文件缺失')))
    if has('7z'):
        cases.append(Case('7Z 到文件夹真实 libarchive 解压', '7z', 'folder', paths['7z'], validate_7z_folder))
        cases.append(Case('7Z 到 ZIP 内容回读', '7z', 'zip', paths['7z'], validate_7z_zip))
    if has('rar'):
        cases.append(Case('RAR 到文件夹多级/Unicode 路径', 'rar', 'folder', paths['rar'], validate_rar_folder))
        cases.append(Case('RAR 到 ZIP 内容回读', 'rar', 'zip', paths['rar'], validate_rar_zip))
    if has('rar_split'):
        cases.append(Case('RAR 分卷完整解压', 'rar', 'folder', paths['rar_split'], validate_split_rar_folder))
    if has('unsafe_zip'):
        cases.append(Case('恶意 ZIP 路径穿越拒绝', 'zip', 'folder', paths['unsafe_zip'], lambda p: None, expected_error='不安全路径'))
    if has('encrypted_zip'):
        cases.append(Case('加密 ZIP 无密码明确拒绝', 'zip', 'folder', paths['encrypted_zip'], lambda p: None, expected_error='请输入解压密码'))
        cases.append(Case('加密 ZIP 密码解压内容回读', 'zip', 'folder', paths['encrypted_zip'], lambda p: require((p / 'secret.txt').read_text(encoding='utf-8') == '机密中文 😀\n', '加密 ZIP 内容丢失'), archive_options={'password': 's3cret!'}))

    if has('wav'):
        cases.append(Case('WAV 到 MP3 音频流', 'wav', 'mp3', paths['wav'], lambda p: require(validate_media_output(p, expected_kind='audio')['hasAudio'], 'WAV→MP3 未检测到音频')))
    if has('amr'):
        cases.append(Case('AMR 到 MP3 真实解码', 'amr', 'mp3', paths['amr'], validate_one_second_audio))
        cases.append(Case('AMR 到 WAV 真实解码', 'amr', 'wav', paths['amr'], validate_one_second_audio))
    if has('mp4'):
        cases.append(Case('MP4 到 MP3 音频提取', 'mp4', 'mp3', paths['mp4'], lambda p: require(validate_media_output(p, expected_kind='audio')['hasAudio'], 'MP4→MP3 未检测到音频')))
        cases.append(Case('MP4 到 GIF 动图输出', 'mp4', 'gif', paths['mp4'], lambda p: require(p.stat().st_size > 1000 and p.read_bytes()[:3] == b'GIF', 'MP4→GIF 输出异常')))
        cases.append(Case('MP4 到 WEBM 视频流', 'mp4', 'webm', paths['mp4'], lambda p: require(validate_media_output(p, expected_kind='video')['hasVideo'], 'MP4→WEBM 未检测到视频')))
    if has('mov_hardware'):
        cases.append(Case('MOV 到 MP4 VideoToolbox 硬件加速', 'mov', 'mp4', paths['mov_hardware'], validate_hardware_mp4, media_options={'hardwareAcceleration': 'videotoolbox', 'videoBitrateKbps': 1200}))
    if has('mkv_complex'):
        cases.append(Case(
            'MKV 到 MP4 保留字幕/章节/元数据', 'mkv', 'mp4', paths['mkv_complex'],
            validate_complex_mp4,
            media_options={'videoMaxWidth': 160, 'videoFrameRate': 12, 'audioSampleRate': 22050},
        ))
        cases.append(Case('MKV 到 WEBM 保留多音轨/多字幕/元数据', 'mkv', 'webm', paths['mkv_complex'], validate_complex_webm))
    if has('m4a_cover'):
        cases.append(Case('M4A 到 MP3 保留封面/中文标题', 'm4a', 'mp3', paths['m4a_cover'], validate_mp3_cover))

    return cases


def validate_csv_contains_zhangsan(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    require('张三' in text and 'remark' in text, 'CSV 内容缺少中文或表头')


def validate_xlsx_contains_zhangsan(path: Path) -> None:
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    values = [cell for row in wb.active.iter_rows(values_only=True) for cell in row]
    require('张三' in values and len(values) >= 8, 'XLSX 内容或行列数异常')


def validate_complex_workbook(path: Path, *, require_chart: bool) -> None:
    import openpyxl  # type: ignore
    workbook = openpyxl.load_workbook(path, data_only=False)
    require(workbook.sheetnames == ['中文数据', 'emoji 😀'], f'多工作表丢失：{workbook.sheetnames}')
    sheet = workbook['中文数据']
    require(sheet['A2'].value == '张三' and str(sheet['C2'].value).startswith('='), '中文或公式丢失')
    require('A5:C5' in {str(item) for item in sheet.merged_cells.ranges}, '合并单元格丢失')
    require(sheet.row_dimensions[3].hidden and sheet.column_dimensions['C'].hidden, '隐藏行列状态丢失')
    require(bool(sheet['A1'].font.bold) and sheet['A1'].fill.fill_type is not None, '单元格样式丢失')
    if require_chart:
        require(len(sheet._charts) >= 1, '图表丢失')
    require(workbook['emoji 😀']['B1'].value == 'مرحبا', 'emoji/RTL 内容丢失')
    workbook.close()


def validate_docx_contains_streamdock(path: Path) -> None:
    from docx import Document  # type: ignore
    text = '\n'.join(p.text for p in Document(str(path)).paragraphs)
    require('StreamDock 转换测试' in text and '张三' in text, 'DOCX 段落内容缺失')


def validate_rich_docx_html(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    require('<table>' in text and '张三' in text, 'DOCX→HTML 表格丢失')
    require('data:image/png;base64,' in text, 'DOCX→HTML 图片未内嵌')
    require('页眉中文' in text and '页脚内容' in text, 'DOCX→HTML 页眉或页脚丢失')
    require('<nav aria-label="文档目录">' in text, 'DOCX→HTML 目录丢失')
    require('请复核这段内容' in text and '审阅人' in text, 'DOCX→HTML 批注丢失')


def validate_image(path: Path, size: tuple[int, int]) -> None:
    from PIL import Image  # type: ignore
    with Image.open(path) as img:
        require(img.size == size, f'图片尺寸异常：{img.size} != {size}')


def validate_gif_frames(path: Path) -> None:
    require(path.is_dir(), 'GIF→PNG 应输出帧目录')
    frames = sorted(path.glob('frame_*.png'))
    require(len(frames) >= 3, f'GIF 帧数不足：{len(frames)}')
    validate_image(frames[0], (64, 64))


def validate_animated_image(path: Path, expected_frames: int) -> None:
    from PIL import Image  # type: ignore
    with Image.open(path) as image:
        require(int(getattr(image, 'n_frames', 1)) == expected_frames, f'动图帧数异常：{getattr(image, "n_frames", 1)}')


def validate_zip_contains_nested(path: Path) -> None:
    require(zipfile.is_zipfile(path), '不是有效 ZIP')
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    require('nested/中文.txt' in names and 'numbers.csv' in names, 'ZIP 目录结构不完整')


def validate_zip_extraction_metadata(path: Path) -> None:
    import stat
    file_path, directory = path / 'nested' / '中文.txt', path / 'nested'
    require(file_path.read_text(encoding='utf-8') == 'archive ok ✅', 'ZIP→folder 文件内容缺失')
    require(stat.S_IMODE(file_path.stat().st_mode) == 0o640, 'ZIP 文件权限未保留')
    require(stat.S_IMODE(directory.stat().st_mode) == 0o750, 'ZIP 目录权限未保留')
    require(abs(file_path.stat().st_mtime - 1600000000) <= 2, 'ZIP 文件时间戳未保留')


def validate_7z_folder(path: Path) -> None:
    hello = path / '7zip-archive' / 'hello'
    require(hello.read_text(encoding='utf-8') == 'hello\n', '7Z 文件内容丢失')
    require((hello.stat().st_mode & 0o777) == 0o644, '7Z 文件权限未保留')
    require(int(hello.stat().st_mtime) == 1579993731, '7Z 文件时间戳未保留')


def validate_7z_zip(path: Path) -> None:
    require(zipfile.is_zipfile(path), '7Z→ZIP 输出格式错误')
    with zipfile.ZipFile(path) as archive:
        require(archive.read('7zip-archive/world') == b'world\n', '7Z→ZIP 成员内容丢失')


def validate_rar_folder(path: Path) -> None:
    require((path / 'sub' / 'dir1' / 'file1.txt').read_text(encoding='utf-8') == 'file1\n', 'RAR 嵌套文件内容丢失')
    require((path / 'sub' / 'with space' / 'long fn.txt').is_file(), 'RAR 空格路径丢失')
    require(any('ȵ' in item.name for item in (path / 'sub').iterdir()), 'RAR Unicode 路径丢失')


def validate_rar_zip(path: Path) -> None:
    require(zipfile.is_zipfile(path), 'RAR→ZIP 输出格式错误')
    with zipfile.ZipFile(path) as archive:
        require(archive.read('sub/dir2/file2.txt') == b'file2\n', 'RAR→ZIP 成员内容丢失')


def validate_split_rar_folder(path: Path) -> None:
    require((path / 'vols' / 'bigfile.txt').stat().st_size == 205000, 'RAR 分卷大文件不完整')
    require((path / 'vols' / 'smallfile.txt').stat().st_size == 2050, 'RAR 分卷小文件不完整')


def ffprobe_json(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [resolve_tool_path('ffprobe'), '-v', 'error', '-show_streams', '-show_chapters', '-show_format', '-of', 'json', str(path)],
        text=True, capture_output=True, check=True, timeout=30,
        env={**os.environ, 'PATH': augmented_path()},
    )
    return json.loads(completed.stdout)


def validate_complex_mp4(path: Path) -> None:
    probe = ffprobe_json(path)
    streams = probe.get('streams') or []
    kinds = {stream.get('codec_type') for stream in streams}
    require({'video', 'audio', 'subtitle'} <= kinds, f'MP4 流不完整：{kinds}')
    require(sum(stream.get('codec_type') == 'audio' for stream in streams) == 2, 'MP4 多音轨丢失')
    require(sum(stream.get('codec_type') == 'subtitle' for stream in streams) == 2, 'MP4 多字幕丢失')
    video = next(stream for stream in streams if stream.get('codec_type') == 'video')
    audio = next(stream for stream in streams if stream.get('codec_type') == 'audio')
    require((video.get('width'), video.get('height'), video.get('r_frame_rate')) == (160, 90, '12/1'), 'MP4 分辨率/帧率参数未生效')
    require(audio.get('sample_rate') == '22050', 'MP4 音频采样率参数未生效')
    require((probe.get('format', {}).get('tags', {}).get('title')) == 'StreamDock 真实媒体', 'MP4 中文元数据丢失')
    require(any(chapter.get('tags', {}).get('title') == '第一章' for chapter in probe.get('chapters') or []), 'MP4 章节丢失')


def validate_mp3_cover(path: Path) -> None:
    probe = ffprobe_json(path)
    streams = probe.get('streams') or []
    require(any(stream.get('codec_type') == 'audio' for stream in streams), 'MP3 音频流丢失')
    require(any(stream.get('disposition', {}).get('attached_pic') == 1 for stream in streams), 'MP3 封面丢失')
    require(probe.get('format', {}).get('tags', {}).get('title') == '中文音频 😀', 'MP3 中文标题丢失')


def validate_complex_webm(path: Path) -> None:
    probe = ffprobe_json(path); streams = probe.get('streams') or []
    require(sum(stream.get('codec_type') == 'audio' for stream in streams) == 2, 'WEBM 多音轨丢失')
    require(sum(stream.get('codec_type') == 'subtitle' for stream in streams) == 2, 'WEBM 多字幕丢失')
    require(probe.get('format', {}).get('tags', {}).get('title') == 'StreamDock 真实媒体', 'WEBM 中文元数据丢失')


def validate_one_second_audio(path: Path) -> None:
    probe = ffprobe_json(path)
    require(any(stream.get('codec_type') == 'audio' for stream in probe.get('streams') or []), '输出缺少音频流')
    duration = float(probe.get('format', {}).get('duration') or 0)
    # MP3 encoders may expose priming/padding in the container duration.  The
    # Ubuntu CI encoder reports 1.152 s for this exact 1 s AMR fixture while
    # the decoded signal remains complete; reject real truncation/expansion,
    # not normal cross-engine padding.
    require(0.85 <= duration <= 1.2, f'音频时长异常：{duration}')


def validate_hardware_mp4(path: Path) -> None:
    probe = ffprobe_json(path)
    video = next((stream for stream in probe.get('streams') or [] if stream.get('codec_type') == 'video'), None)
    require(video is not None and video.get('codec_name') == 'h264', '硬件转码未生成 H.264 视频流')


def run_case(case: Case, output_dir: Path) -> CaseResult:
    start = time.perf_counter()
    result = convert_file(
        case.input_path, case.input_path.name, case.source, case.target, output_dir,
        naming_strategy='append', image_quality=case.image_quality, media_options=case.media_options, archive_options=case.archive_options,
    )
    elapsed = round(time.perf_counter() - start, 3)
    if case.expected_error:
        if not result.success and result.error and case.expected_error in result.error:
            return CaseResult(case.name, case.source, case.target, 'PASS', elapsed, error=result.error, notes='按预期拒绝异常输入')
        return CaseResult(case.name, case.source, case.target, 'FAIL', elapsed, output_path=str(result.output_path) if result.output_path else None, error=f'期望错误包含 {case.expected_error!r}，实际 success={result.success}, error={result.error!r}')
    if not result.success or not result.output_path:
        return CaseResult(case.name, case.source, case.target, 'FAIL', elapsed, error=result.error or '未生成输出')
    try:
        case.validate(result.output_path)
    except Exception as exc:
        return CaseResult(case.name, case.source, case.target, 'FAIL', elapsed, output_path=str(result.output_path), error=str(exc), validation=result.validation or {}, notes=case.notes)
    return CaseResult(case.name, case.source, case.target, 'PASS', elapsed, output_path=str(result.output_path), validation=result.validation or {}, notes=case.notes)


def main() -> int:
    parser = argparse.ArgumentParser(description='StreamDock 文件转换鲁棒性/准确性验证脚本')
    parser.add_argument('--workdir', type=Path, default=None, help='工作目录，默认创建临时目录')
    parser.add_argument('--keep', action='store_true', help='保留工作目录，便于排查')
    parser.add_argument('--report', type=Path, default=ROOT / 'report_figures' / 'conversion_robustness_latest.json', help='JSON 报告输出路径')
    args = parser.parse_args()
    artifacts_retained = bool(args.keep or args.workdir)

    temp_ctx = None
    if args.workdir:
        workdir = args.workdir.expanduser().resolve()
        workdir.mkdir(parents=True, exist_ok=True)
    elif args.keep:
        workdir = Path(tempfile.mkdtemp(prefix='streamdock-conversion-robustness-kept-'))
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix='streamdock-conversion-robustness-')
        workdir = Path(temp_ctx.name)
    output_dir = workdir / 'outputs'; output_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = generate_fixtures(workdir)
        cases = build_cases(paths)
        contract = json.loads(RELEASE_CONTRACT.read_text(encoding='utf-8'))
        required_names = set(contract['robustnessCases']['required'])
        if sys.platform == 'darwin':
            required_names.update(contract['robustnessCases'].get('darwinRequired') or [])
        actual_names = {case.name for case in cases}
        missing_cases = sorted(required_names - actual_names)
        unexpected_cases = sorted(actual_names - required_names - set(contract['robustnessCases'].get('darwinRequired') or []))
        results = [run_case(case, output_dir) for case in cases]
        by_name = {item.name: item for item in results}
        low = by_name.get('PNG 到 JPEG 低质量参数')
        high = by_name.get('PNG 到 JPEG 高质量参数')
        if low and high and low.status == high.status == 'PASS' and low.output_path and high.output_path:
            low_size, high_size = Path(low.output_path).stat().st_size, Path(high.output_path).stat().st_size
            low.validation['quality'] = 20; low.validation['sizeBytes'] = low_size
            high.validation['quality'] = 95; high.validation['sizeBytes'] = high_size
            if low_size >= high_size:
                low.status = 'FAIL'; low.error = f'图片质量参数未影响输出大小：{low_size} >= {high_size}'
        passed = sum(1 for item in results if item.status == 'PASS')
        failed = [item for item in results if item.status != 'PASS']
        serialized_results = []
        for item in results:
            serialized = dict(item.__dict__)
            if not artifacts_retained:
                serialized['output_path'] = None
            serialized_results.append(serialized)
        report = {
            'generatedAt': time.strftime('%Y-%m-%d %H:%M:%S'),
            'workdir': str(workdir) if artifacts_retained else None,
            'artifactsRetained': artifacts_retained,
            'total': len(results),
            'passed': passed,
            'failed': len(failed),
            'coverage': {
                'required': len(required_names), 'actual': len(actual_names),
                'missing': missing_cases, 'unexpected': unexpected_cases,
            },
            'results': serialized_results,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

        print(f'工作目录: {workdir}')
        print(f'报告文件: {args.report}')
        print(f'转换用例: {passed}/{len(results)} 通过')
        for item in results:
            symbol = '✓' if item.status == 'PASS' else '✗'
            print(f'{symbol} {item.name} [{item.source}->{item.target}] {item.elapsed_seconds:.3f}s')
            if item.error and item.status != 'PASS':
                print(f'  error: {item.error}')
        if failed:
            print('\n失败用例请查看 JSON 报告中的 output_path/error。')
            return 1
        if missing_cases or unexpected_cases:
            print(f'\n固定用例合同不匹配：missing={missing_cases}, unexpected={unexpected_cases}')
            return 1
        return 0
    finally:
        if temp_ctx:
            temp_ctx.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
