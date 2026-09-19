import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from converters.adapters.archive import convert_archive
from converters.adapters.data import dict_to_xml, read_xlsx_rows, xml_to_dict
from converters.adapters.document_basic import _libreoffice_convert, _text_to_rtf
from converters.sniff import sniff_file_format, validate_declared_format
from converters.adapters.image import convert_image
from converters.comparison import build_conversion_comparison
from converters.adapters.media import convert_media
from converters.models import ConversionLevel
from converters.pipeline import convert_file
from converters.executor import convert_file_with_timeout
from converters.registry import find_capability, infer_input_format, list_capabilities


class ConverterRegistryTests(unittest.TestCase):
    def test_registry_contains_large_first_version_capability_matrix(self):
        capabilities = list_capabilities()
        self.assertEqual(len(capabilities), len({capability.key for capability in capabilities}))
        self.assertGreaterEqual(len([c for c in capabilities if c.level == ConversionLevel.STABLE]), 45)
        self.assertGreaterEqual(len([c for c in capabilities if c.level == ConversionLevel.BASIC]), 15)
        self.assertGreaterEqual(len([c for c in capabilities if c.level == ConversionLevel.VENDOR]), 10)

    def test_registry_contains_representative_paths(self):
        self.assertEqual(find_capability('csv', 'xlsx').level, ConversionLevel.STABLE)
        self.assertEqual(find_capability('png', 'webp').level, ConversionLevel.STABLE)
        self.assertEqual(find_capability('mp4', 'mp3').level, ConversionLevel.STABLE)
        self.assertEqual(find_capability('md', 'pdf').level, ConversionLevel.BASIC)
        self.assertEqual(find_capability('pdf', 'docx').level, ConversionLevel.VENDOR)
        self.assertEqual(find_capability('pptx', 'png').level, ConversionLevel.VENDOR)



    def test_registry_expands_non_pdf_document_capabilities(self):
        required = {
            ('txt', 'docx'),
            ('md', 'docx'),
            ('html', 'docx'),
            ('rtf', 'txt'),
            ('rtf', 'html'),
            ('rtf', 'docx'),
            ('docx', 'md'),
            ('docx', 'rtf'),
            ('odt', 'docx'),
            ('doc', 'docx'),
            ('ppt', 'pptx'),
            ('xls', 'xlsx'),
            ('ods', 'xlsx'),
            ('epub', 'txt'),
            ('epub', 'html'),
        }
        for source, target in required:
            with self.subTest(path=f'{source}->{target}'):
                capability = find_capability(source, target)
                self.assertIsNotNone(capability)
                self.assertNotEqual(capability.level, ConversionLevel.VENDOR)
                self.assertNotEqual(capability.target, 'pdf')



    def test_registry_expands_common_non_pdf_media_image_subtitle_paths(self):
        required = {
            ('avi', 'mp4'),
            ('flv', 'mp4'),
            ('m4v', 'mp4'),
            ('3gp', 'mp4'),
            ('ts', 'mp4'),
            ('aiff', 'mp3'),
            ('wma', 'mp3'),
            ('amr', 'mp3'),
            ('png', 'ico'),
            ('ico', 'png'),
            ('ppm', 'png'),
            ('png', 'ppm'),
            ('lrc', 'srt'),
            ('lrc', 'vtt'),
            ('gz', 'folder'),
            ('bz2', 'folder'),
        }
        for source, target in required:
            with self.subTest(path=f'{source}->{target}'):
                capability = find_capability(source, target)
                self.assertIsNotNone(capability)
                self.assertNotEqual(capability.level, ConversionLevel.VENDOR)
                self.assertNotEqual(capability.target, 'pdf')

    def test_real_7z_fixture_extracts_with_content_and_metadata(self):
        if not shutil.which('bsdtar'):
            self.skipTest('bsdtar is not installed')
        fixture = Path(__file__).parent / 'fixtures' / 'real' / 'archive.7z'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            logs = convert_archive('7z', 'folder', fixture, output)
            hello = output / '7zip-archive' / 'hello'

            self.assertEqual(hello.read_text(encoding='utf-8'), 'hello\n')
            self.assertEqual(hello.stat().st_mode & 0o777, 0o644)
            self.assertTrue(any('libarchive' in line for line in logs))

    def test_real_rar_fixture_extracts_nested_unicode_content(self):
        if not shutil.which('bsdtar'):
            self.skipTest('bsdtar is not installed')
        fixture = Path(__file__).parent / 'fixtures' / 'real' / 'archive.rar'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            convert_archive('rar', 'folder', fixture, output)

            self.assertEqual((output / 'sub' / 'dir1' / 'file1.txt').read_text(encoding='utf-8'), 'file1\n')
            self.assertTrue((output / 'sub' / 'with space' / 'long fn.txt').is_file())
            self.assertTrue(any('ȵ' in item.name for item in (output / 'sub').iterdir()))

    def test_infer_input_format_handles_compound_extensions(self):
        self.assertEqual(infer_input_format('archive.tar.gz'), 'tar.gz')
        self.assertEqual(infer_input_format('rows.ndjson'), 'ndjson')
        self.assertEqual(infer_input_format('table.CSV'), 'csv')


class ConverterPipelineTests(unittest.TestCase):
    def test_zip_extraction_enforces_member_and_size_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'many.zip'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('first.txt', '1234')
                zf.writestr('second.txt', '5678')
            with patch('converters.adapters.archive.MAX_ARCHIVE_MEMBERS', 1):
                with self.assertRaisesRegex(RuntimeError, '成员过多'):
                    convert_archive('zip', 'folder', archive, root / 'members')
            with patch('converters.adapters.archive.MAX_ARCHIVE_EXTRACTED_BYTES', 4):
                with self.assertRaisesRegex(RuntimeError, '解压后大小过大'):
                    convert_archive('zip', 'folder', archive, root / 'size')
    def test_table_comparison_reports_schema_rows_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.csv'
            output = root / 'output.json'
            source.write_text('name,score\n中文,98.5\n', encoding='utf-8')
            output.write_text('[{"name": "中文", "score": "98.5"}]', encoding='utf-8')
            comparison = build_conversion_comparison('csv', 'json', source, output)

        self.assertTrue(comparison['available'])
        self.assertEqual(comparison['kind'], 'table')
        self.assertEqual(comparison['before']['rows'], 1)
        self.assertEqual(comparison['after']['preview'][0][0], '中文')
        self.assertEqual(comparison['rowDelta'], 0)
        self.assertEqual(comparison['changedPreviewCells'], 0)

    def test_table_comparison_reports_workbook_structure(self):
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, Reference

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); before_path = root / 'before.xlsx'; after_path = root / 'after.xlsx'
            workbook = Workbook(); sheet = workbook.active; sheet.append(['v']); sheet.append([1]); sheet['A3'] = '=A2+1'
            sheet.merge_cells('A4:B4'); sheet.row_dimensions[2].hidden = True
            chart = BarChart(); chart.add_data(Reference(sheet, min_col=1, min_row=1, max_row=2), titles_from_data=True); sheet.add_chart(chart, 'D2')
            workbook.create_sheet('第二表')['A1'] = '中文'; workbook.save(before_path)
            Workbook().save(after_path)

            comparison = build_conversion_comparison('xlsx', 'xlsx', before_path, after_path)

            self.assertTrue(comparison['workbookStructureChanged'])
            self.assertEqual(comparison['before']['sheets'], 2)
            self.assertEqual(comparison['before']['formulas'], 1)
            self.assertEqual(comparison['before']['mergedRanges'], 1)
            self.assertEqual(comparison['before']['hiddenRows'], 1)
            self.assertEqual(comparison['before']['charts'], 1)

    def test_text_comparison_uses_rendered_rtf_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.txt'
            output = root / 'output.rtf'
            source.write_text('第一行中文 😀\n', encoding='utf-8')
            output.write_text(_text_to_rtf('第一行中文 😀\n'), encoding='ascii')
            comparison = build_conversion_comparison('txt', 'rtf', source, output)

        self.assertTrue(comparison['available'])
        self.assertEqual(comparison['kind'], 'text')
        self.assertIn('第一行中文 😀', comparison['after']['sample'])
        self.assertEqual(comparison['addedLines'], 0)
        self.assertEqual(comparison['removedLines'], 0)

    def test_image_conversion_preserves_icc_and_reports_lossy_quality(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.png'
            output = root / 'output.webp'
            Image.new('RGBA', (12, 8), (20, 40, 60, 128)).save(source, icc_profile=b'profile-data')
            logs = convert_image('png', 'webp', source, output)
            with Image.open(output) as converted:
                self.assertEqual(converted.size, (12, 8))
                self.assertEqual(converted.info.get('icc_profile'), b'profile-data')

        self.assertTrue(any('质量' in line for line in logs))

    def test_multiframe_tiff_to_png_preserves_all_frames_as_apng(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'animation.tiff'
            output = root / 'animation.png'
            first = Image.new('RGB', (10, 6), (255, 0, 0))
            second = Image.new('RGB', (10, 6), (0, 0, 255))
            first.save(source, save_all=True, append_images=[second])

            logs = convert_image('tiff', 'png', source, output)
            with Image.open(output) as converted:
                self.assertEqual(converted.n_frames, 2)
                converted.seek(1)
                self.assertEqual(converted.convert('RGB').getpixel((0, 0)), (0, 0, 255))

        self.assertTrue(any('APNG' in line for line in logs))

    def test_multiframe_tiff_to_jpg_refuses_silent_frame_loss(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'animation.tiff'
            first = Image.new('RGB', (10, 6), 'red'); second = Image.new('RGB', (10, 6), 'blue')
            first.save(source, save_all=True, append_images=[second])

            with self.assertRaisesRegex(RuntimeError, '无法完整保留所有帧'):
                convert_image('tiff', 'jpg', source, root / 'output.jpg')

    def test_apng_to_gif_preserves_all_frames(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'animation.png'
            output = root / 'animation.gif'
            frames = [Image.new('RGBA', (9, 7), color) for color in ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))]
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=[80, 90, 100], loop=0)

            logs = convert_image('png', 'gif', source, output)
            with Image.open(output) as converted:
                self.assertEqual(converted.n_frames, 3)

        self.assertTrue(any('3 帧' in line for line in logs))
    def test_conversion_timeout_terminates_worker_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'sample.csv'
            source.write_text('name\nAda\n', encoding='utf-8')
            result = convert_file_with_timeout(
                source,
                source.name,
                'csv',
                'json',
                root,
                timeout_seconds=0,
            )
        self.assertFalse(result.success)
        self.assertIn('超时', result.error)

    def test_pipeline_converts_csv_to_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'sample.csv'
            input_file.write_text('name,age\nAda,12\n', encoding='utf-8')

            result = convert_file(input_file, input_file.name, 'csv', 'json', tmp_path)

            self.assertTrue(result.success)
            self.assertIsNotNone(result.output_path)
            self.assertTrue(result.output_path.exists())
            self.assertIn('Ada', result.output_path.read_text(encoding='utf-8'))

    def test_pipeline_converts_json_to_toml_when_tomllib_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'settings.json'
            source.write_text(json.dumps({'app': {'name': 'StreamDock', 'port': 8002}}), encoding='utf-8')

            result = convert_file(source, source.name, 'json', 'toml', root)

            self.assertTrue(result.success, result.error)
            import tomllib
            parsed = tomllib.loads(result.output_path.read_text(encoding='utf-8'))
            self.assertEqual(parsed['app']['name'], 'StreamDock')
            self.assertEqual(parsed['app']['port'], 8002)

    def test_json_array_to_toml_reports_a_supported_user_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'items.json'
            source.write_text('[{"name": "StreamDock"}]', encoding='utf-8')

            result = convert_file(source, source.name, 'json', 'toml', root)

        self.assertFalse(result.success)
        self.assertIn('顶层数组', result.error)
        self.assertNotIn('list indices', result.error)

    def test_tabular_txt_output_is_accepted_as_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'items.json'
            source.write_text('[{"name": "中文", "note": "emoji 😀"}]', encoding='utf-8')

            result = convert_file(source, source.name, 'json', 'txt', root)

            self.assertTrue(result.success, result.error)
            self.assertIn('\t', result.output_path.read_text(encoding='utf-8'))


    def test_rtf_writer_uses_unicode_escapes_for_cjk_and_emoji(self):
        rtf = _text_to_rtf('第一行中文 😀\\n')

        self.assertTrue(rtf.isascii())
        self.assertIn(r'\u31532?', rtf)
        self.assertIn(r'\u-10179?', rtf)  # high surrogate for U+1F600

    def test_sniff_recognizes_ndjson_amr_and_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ndjson = root / 'rows.ndjson'
            ndjson.write_text('{"name":"甲","note":"a,b"}\n{"name":"乙"}\n', encoding='utf-8')
            amr = root / 'sample.amr'
            amr.write_bytes(b'#!AMR\n\x00\x01')
            archive = root / 'sample.tar'
            payload = b'hello'
            with tarfile.open(archive, 'w') as tf:
                info = tarfile.TarInfo('hello.txt')
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))

            self.assertEqual(sniff_file_format(ndjson), 'ndjson')
            self.assertEqual(sniff_file_format(amr), 'amr')
            self.assertEqual(sniff_file_format(archive), 'tar')
            self.assertTrue(validate_declared_format(ndjson, 'ndjson')[0])

    def test_xlsx_reader_preserves_zero_header(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'headers.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append([0, None])
            sheet.append(['value', 'fallback'])
            workbook.save(path)

            rows = read_xlsx_rows(path)

        self.assertEqual(rows, [{'0': 'value', 'column_2': 'fallback'}])

    def test_xlsx_formula_without_cached_value_has_clear_export_policy(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'formula.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(['total'])
            sheet.append(['=SUM(1, 2)'])
            workbook.save(path)
            with self.assertRaisesRegex(RuntimeError, '仅导出计算值'):
                read_xlsx_rows(path)

    def test_xlsx_text_export_rejects_multiple_nonempty_sheets(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'multi.xlsx'
            workbook = Workbook(); workbook.active.append(['sheet-one'])
            workbook.create_sheet('第二表').append(['sheet-two'])
            workbook.save(source)

            result = convert_file(source, source.name, 'xlsx', 'csv', root)

            self.assertFalse(result.success)
            self.assertIn('多个非空工作表', result.error)

    def test_xlsx_reader_handles_missing_worksheet_dimensions(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / 'original.xlsx'
            source = root / 'missing-dimensions.xlsx'
            workbook = Workbook(); workbook.active.append(['sheet-one'])
            workbook.create_sheet('第二表').append(['sheet-two'])
            workbook.save(original)
            with zipfile.ZipFile(original) as incoming, zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as outgoing:
                for info in incoming.infolist():
                    data = incoming.read(info.filename)
                    if info.filename.startswith('xl/worksheets/sheet') and info.filename.endswith('.xml'):
                        data = re.sub(br'<dimension\s+ref="[^"]+"\s*/>', b'', data)
                    outgoing.writestr(info, data)

            with self.assertRaisesRegex(RuntimeError, '多个非空工作表'):
                read_xlsx_rows(source)

    def test_xlsx_csv_logs_unrepresentable_structure_downgrades(self):
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, Reference
        from openpyxl.styles import Font

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'structured.xlsx'
            workbook = Workbook(); sheet = workbook.active
            sheet.append(['name', 'score']); sheet.append(['张三', 98]); sheet.append(['李四', 87])
            sheet['A1'].font = Font(bold=True); sheet.merge_cells('A4:B4'); sheet['A4'] = '合并'
            sheet.row_dimensions[3].hidden = True
            chart = BarChart(); chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True); sheet.add_chart(chart, 'D2')
            workbook.save(source)

            result = convert_file(source, source.name, 'xlsx', 'csv', root)

            self.assertTrue(result.success, result.error)
            joined = '\n'.join(result.logs)
            for keyword in ('合并单元格', '隐藏行列', '图表对象', '单元格样式'):
                self.assertIn(keyword, joined)

    def test_xml_reader_preserves_mixed_content_text(self):
        root = ET.fromstring('<root>leading text<child>value</child></root>')

        parsed = xml_to_dict(root)

        self.assertEqual(parsed, {'root': {'#text': 'leading text', 'child': 'value'}})
        rebuilt = dict_to_xml('root', parsed['root'])
        self.assertEqual(rebuilt.text, 'leading text')
        self.assertEqual(rebuilt.findtext('child'), 'value')



    def test_pipeline_converts_txt_to_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'note.txt'
            input_file.write_text('第一行\n第二行\n', encoding='utf-8')

            result = convert_file(input_file, input_file.name, 'txt', 'docx', tmp_path)

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.output_path.exists())
            from docx import Document
            doc = Document(str(result.output_path))
            self.assertIn('第一行', '\n'.join(p.text for p in doc.paragraphs))

    def test_pipeline_converts_markdown_to_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'guide.md'
            input_file.write_text('# 标题\n\n正文内容', encoding='utf-8')

            result = convert_file(input_file, input_file.name, 'md', 'docx', tmp_path)

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.output_path.exists())
            from docx import Document
            doc = Document(str(result.output_path))
            text = '\n'.join(p.text for p in doc.paragraphs)
            self.assertIn('标题', text)
            self.assertIn('正文内容', text)

    def test_pipeline_converts_chinese_markdown_table_to_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / '产品思维.md'
            source.write_text('# 产品思维\n\n| 序号 | 项目方向 | 简介 |\n| --- | --- | --- |\n| 1 | 推荐系统 | 中文内容可读 |\n', encoding='utf-8')
            result = convert_file(source, source.name, 'md', 'html', root)
            self.assertTrue(result.success, result.error)
            rendered = result.output_path.read_text(encoding='utf-8')
            self.assertIn('<table>', rendered)
            self.assertIn('中文内容可读', rendered)

    def test_pipeline_converts_chinese_markdown_table_to_readable_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / '产品思维.md'
            source.write_text('# 产品思维\n\n| 序号 | 项目方向 | 简介 |\n| --- | --- | --- |\n| 1 | 推荐系统 | 中文内容可读 |\n', encoding='utf-8')
            result = convert_file(source, source.name, 'md', 'pdf', root)
            self.assertTrue(result.success, result.error)
            from pypdf import PdfReader
            extracted = '\n'.join(page.extract_text() or '' for page in PdfReader(str(result.output_path)).pages)
            self.assertIn('产品思维', extracted)
            self.assertIn('中文内容可读', extracted)

    def test_pipeline_converts_html_structure_to_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'page.html'
            source.write_text(
                '<h1>Title</h1><p>Read the <a href="https://example.test">guide</a>.</p><ul><li>First</li></ul>',
                encoding='utf-8',
            )

            result = convert_file(source, source.name, 'html', 'md', root)

            self.assertTrue(result.success, result.error)
            markdown = result.output_path.read_text(encoding='utf-8')
            self.assertIn('# Title', markdown)
            self.assertIn('[guide](https://example.test)', markdown)
            self.assertIn('First', markdown)

    def test_pipeline_converts_rtf_to_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'legacy.rtf'
            input_file.write_text(r'{\rtf1\ansi 第一行\par 第二行}', encoding='utf-8')

            result = convert_file(input_file, input_file.name, 'rtf', 'txt', tmp_path)

            self.assertTrue(result.success, result.error)
            content = result.output_path.read_text(encoding='utf-8')
            self.assertIn('第一行', content)
            self.assertIn('第二行', content)

    def test_pipeline_converts_epub_to_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'book.epub'
            from ebooklib import epub
            book = epub.EpubBook()
            book.set_identifier('streamdock-test')
            book.set_title('测试书')
            book.set_language('zh')
            chapter = epub.EpubHtml(title='第一章', file_name='chapter.xhtml', lang='zh')
            chapter.content = '<html><body><h1>第一章</h1><p>正文内容</p></body></html>'
            book.add_item(chapter)
            book.toc = (chapter,)
            book.spine = ['nav', chapter]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            epub.write_epub(str(input_file), book)

            result = convert_file(input_file, input_file.name, 'epub', 'html', tmp_path)

            self.assertTrue(result.success, result.error)
            content = result.output_path.read_text(encoding='utf-8')
            self.assertIn('第一章', content)
            self.assertIn('正文内容', content)



    def test_pipeline_converts_lrc_to_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'song.lrc'
            input_file.write_text('[00:01.20]第一句\n[00:03.00]第二句\n', encoding='utf-8')

            result = convert_file(input_file, input_file.name, 'lrc', 'srt', tmp_path)

            self.assertTrue(result.success, result.error)
            content = result.output_path.read_text(encoding='utf-8')
            self.assertIn('00:00:01,200 --> 00:00:03,000', content)
            self.assertIn('第一句', content)

    def test_docx_to_html_preserves_table_image_header_and_footer(self):
        from docx import Document
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'rich.docx'
            image_path = root / 'figure.png'
            Image.new('RGB', (8, 6), 'red').save(image_path)
            document = Document()
            document.sections[0].header.paragraphs[0].text = '页眉中文'
            document.add_heading('丰富文档', level=1)
            paragraph = document.add_paragraph('正文 emoji 😀')
            document.add_comment(paragraph.runs[0], text='请复核这段内容', author='审阅人', initials='QA')
            paragraph.add_run().add_picture(str(image_path))
            table = document.add_table(rows=2, cols=2)
            table.cell(0, 0).text = '姓名'; table.cell(0, 1).text = '分数'
            table.cell(1, 0).text = '张三'; table.cell(1, 1).text = '98'
            document.sections[0].footer.paragraphs[0].text = '页脚内容'
            document.save(source)

            result = convert_file(source, source.name, 'docx', 'html', root)

            self.assertTrue(result.success, result.error)
            content = result.output_path.read_text(encoding='utf-8')
            self.assertIn('<table>', content)
            self.assertIn('张三', content)
            self.assertIn('data:image/png;base64,', content)
            self.assertIn('页眉中文', content)
            self.assertIn('页脚内容', content)
            self.assertIn('<nav aria-label="文档目录">', content)
            self.assertIn('请复核这段内容', content)
            self.assertIn('审阅人', content)

    def test_xml_external_entity_is_rejected_before_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'unsafe.xml'
            source.write_text(
                '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root>&xxe;</root>',
                encoding='utf-8',
            )

            result = convert_file(source, source.name, 'xml', 'json', root)

            self.assertFalse(result.success)
            self.assertIn('XML 外部实体', result.error)

    def test_svg_script_and_external_resource_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'unsafe.svg'
            source.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><image href="https://example.invalid/x.png"/></svg>',
                encoding='utf-8',
            )

            result = convert_file(source, source.name, 'svg', 'png', root)

            self.assertFalse(result.success)
            self.assertIn('SVG 包含脚本', result.error)

    def test_svg_character_reference_cannot_hide_external_file_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'unsafe-encoded.svg'
            source.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><image href="f&#105;le:///mock/a.png"/></svg>',
                encoding='utf-8',
            )

            result = convert_file(source, source.name, 'svg', 'png', root)

            self.assertFalse(result.success)
            self.assertIn('SVG 包含外部资源引用', result.error)

    def test_docx_external_relationship_is_rejected_before_conversion(self):
        from docx import Document

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = root / 'clean.docx'
            source = root / 'external.docx'
            document = Document(); document.add_paragraph('正文'); document.save(clean)
            with zipfile.ZipFile(clean) as incoming, zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as outgoing:
                for info in incoming.infolist():
                    data = incoming.read(info.filename)
                    if info.filename == 'word/_rels/document.xml.rels':
                        data = data.replace(
                            b'</Relationships>',
                            b'<Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/" TargetMode="External"/></Relationships>',
                        )
                    outgoing.writestr(info, data)

            result = convert_file(source, source.name, 'docx', 'html', root)

            self.assertFalse(result.success)
            self.assertIn('外部链接关系', result.error)

    def test_pipeline_converts_png_to_ico(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'icon.png'
            from PIL import Image
            Image.new('RGBA', (32, 32), (255, 0, 0, 255)).save(input_file)

            result = convert_file(input_file, input_file.name, 'png', 'ico', tmp_path)

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.output_path.exists())
            self.assertGreater(result.output_path.stat().st_size, 0)

    def test_pipeline_extracts_gz_to_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'hello.txt.gz'
            import gzip
            with gzip.open(input_file, 'wb') as fh:
                fh.write('hello gzip'.encode('utf-8'))

            result = convert_file(input_file, input_file.name, 'gz', 'folder', tmp_path)

            self.assertTrue(result.success, result.error)
            extracted = result.output_path / 'hello.txt'
            self.assertTrue(extracted.exists())
            self.assertEqual(extracted.read_text(encoding='utf-8'), 'hello gzip')

    def test_archive_extraction_rejects_tar_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / 'evil.tar'
            data = b'tar-slip'
            info = tarfile.TarInfo('../pwned.txt')
            info.size = len(data)
            with tarfile.open(archive, 'w') as tf:
                tf.addfile(info, io.BytesIO(data))

            with self.assertRaisesRegex(RuntimeError, '不安全路径'):
                convert_archive('tar', 'folder', archive, tmp_path / 'out')
            self.assertFalse((tmp_path / 'pwned.txt').exists())

    def test_archive_extraction_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / 'evil.zip'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('../pwned.txt', 'zip-slip')

            with self.assertRaisesRegex(RuntimeError, '不安全路径'):
                convert_archive('zip', 'folder', archive, tmp_path / 'out')
            self.assertFalse((tmp_path / 'pwned.txt').exists())

    def test_archive_extraction_rejects_extreme_compression_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'bomb.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('repeated.bin', b'0' * (2 * 1024 * 1024))

            with self.assertRaisesRegex(RuntimeError, '压缩炸弹'):
                convert_archive('zip', 'folder', archive, root / 'out')

    def test_archive_packing_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'source'
            folder.mkdir()
            (folder / 'real.txt').write_text('safe', encoding='utf-8')
            try:
                (folder / 'alias.txt').symlink_to(folder / 'real.txt')
            except OSError:
                self.skipTest('current filesystem does not support symlinks')

            with self.assertRaisesRegex(RuntimeError, '符号链接'):
                convert_archive('folder', 'zip', folder, root / 'out.zip')

    def test_archive_extraction_rejects_tar_special_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'special.tar'
            info = tarfile.TarInfo('named-pipe')
            info.type = tarfile.FIFOTYPE
            with tarfile.open(archive, 'w') as tf:
                tf.addfile(info)

            with self.assertRaisesRegex(RuntimeError, '特殊文件'):
                convert_archive('tar', 'folder', archive, root / 'out')

    def test_archive_conversion_removes_intermediate_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'source.zip'
            output = root / 'converted.tar'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('hello.txt', 'hello')

            convert_archive('zip', 'tar', archive, output)

            self.assertTrue(output.is_file())
            self.assertFalse(output.with_suffix('').exists())

    def test_archive_conversion_cleans_intermediate_directory_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'source.tar'
            output = root / 'converted.zip'
            data = b'hello'
            info = tarfile.TarInfo('hello.txt')
            info.size = len(data)
            with tarfile.open(archive, 'w') as tf:
                tf.addfile(info, io.BytesIO(data))

            with patch('converters.adapters.archive._folder_to_zip', side_effect=RuntimeError('zip failed')):
                with self.assertRaisesRegex(RuntimeError, 'zip failed'):
                    convert_archive('tar', 'zip', archive, output)

            self.assertFalse(output.with_suffix('').exists())

    def test_single_file_archive_uses_streaming_copy(self):
        import gzip

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'large.txt.gz'
            with gzip.open(archive, 'wb') as handle:
                handle.write(b'x' * (1024 * 1024))

            with patch('converters.adapters.archive.shutil.copyfileobj', wraps=shutil.copyfileobj) as copy:
                convert_archive('gz', 'folder', archive, root / 'out')

            copy.assert_called_once()
            self.assertEqual((root / 'out' / 'large.txt').stat().st_size, 1024 * 1024)

    def test_direct_gif_conversion_rejects_silent_first_frame_loss(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'animated.gif'
            frames = [Image.new('RGB', (4, 4), color) for color in ('red', 'blue')]
            frames[0].save(source, save_all=True, append_images=frames[1:])

            with self.assertRaisesRegex(RuntimeError, 'PNG 帧序列'):
                convert_image('gif', 'jpg', source, root / 'output.jpg')

    def test_netpbm_targets_use_semantic_pixel_modes(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.png'
            Image.new('RGB', (3, 3), 'red').save(source)

            pgm = root / 'output.pgm'
            pbm = root / 'output.pbm'
            convert_image('png', 'pgm', source, pgm)
            convert_image('png', 'pbm', source, pbm)

            self.assertEqual(pgm.read_bytes()[:2], b'P5')
            self.assertEqual(pbm.read_bytes()[:2], b'P4')

    def test_pipeline_rejects_vendor_only_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'sample.pdf'
            input_file.write_bytes(b'%PDF-1.4')

            result = convert_file(input_file, input_file.name, 'pdf', 'docx', tmp_path)

            self.assertFalse(result.success)
            self.assertTrue(result.vendor_recommendations)
            self.assertIn('推荐厂商', result.error)

    def test_media_conversion_passes_timeout_to_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'demo.mp4'
            output_file = tmp_path / 'demo.mp3'
            input_file.write_bytes(b'fake')

            with patch('converters.adapters.media.shutil.which', return_value='/usr/bin/ffmpeg'):
                with patch('converters.adapters.media.subprocess.run') as mocked_run:
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stderr = ''

                    convert_media('mp4', 'mp3', input_file, output_file, options={'audioBitrateKbps': 96, 'audioSampleRate': 22050})

            self.assertIn('timeout', mocked_run.call_args.kwargs)
            self.assertGreater(mocked_run.call_args.kwargs['timeout'], 0)
            self.assertIn('-map_metadata', mocked_run.call_args.args[0])
            self.assertIn('-map_chapters', mocked_run.call_args.args[0])
            self.assertIn('96k', mocked_run.call_args.args[0])
            self.assertIn('22050', mocked_run.call_args.args[0])

    def test_media_conversion_maps_cover_only_when_probe_finds_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'demo.m4a'
            output_file = tmp_path / 'demo.mp3'
            input_file.write_bytes(b'fake')

            with patch('converters.adapters.media.shutil.which', return_value='/usr/bin/tool'):
                with patch('converters.adapters.media._attached_picture_stream', return_value=2):
                    with patch('converters.adapters.media.subprocess.run') as mocked_run:
                        mocked_run.return_value.returncode = 0
                        mocked_run.return_value.stderr = ''
                        convert_media('m4a', 'mp3', input_file, output_file)

            command = mocked_run.call_args.args[0]
            self.assertIn('0:2', command)
            self.assertIn('attached_pic', command)

    def test_video_conversion_maps_subtitles_and_uses_container_codec(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'demo.mkv'
            output_file = tmp_path / 'demo.mp4'
            input_file.write_bytes(b'fake')

            with patch('converters.adapters.media.shutil.which', return_value='/usr/bin/ffmpeg'):
                with patch('converters.adapters.media.subprocess.run') as mocked_run:
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stderr = ''
                    convert_media('mkv', 'mp4', input_file, output_file)

            command = mocked_run.call_args.args[0]
            self.assertIn('0:s?', command)
            self.assertEqual(command[command.index('-c:s') + 1], 'mov_text')

    def test_liberoffice_conversion_reports_timeout_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'demo.docx'
            input_file.write_bytes(b'fake')

            with patch('converters.adapters.document_basic.shutil.which', return_value='/usr/bin/soffice'):
                with patch(
                    'converters.adapters.document_basic.subprocess.run',
                    side_effect=subprocess.TimeoutExpired(cmd='soffice', timeout=1),
                ):
                    with self.assertRaisesRegex(RuntimeError, '超时'):
                        _libreoffice_convert(input_file, tmp_path, 'pdf')

    def test_libreoffice_csv_conversion_requests_utf8_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_file = tmp_path / 'demo.xls'
            input_file.write_bytes(b'fake')
            expected = tmp_path / 'demo.csv'

            with patch('converters.adapters.document_basic.shutil.which', return_value='/usr/bin/soffice'):
                with patch('converters.adapters.document_basic.subprocess.run') as mocked_run:
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stderr = ''
                    mocked_run.return_value.stdout = ''
                    expected.write_text('姓名,emoji\n中文,😀\n', encoding='utf-8')
                    produced = _libreoffice_convert(input_file, tmp_path, 'csv')

        self.assertEqual(produced, expected)
        self.assertIn('csv:Text - txt - csv (StarCalc):44,34,76,1', mocked_run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
