import tempfile
import unittest
from pathlib import Path

from converters.batch import BatchInput, convert_batch_files, validate_batch_route


class BatchConversionTests(unittest.TestCase):
    def test_validate_batch_route_accepts_identical_sources(self):
        validation = validate_batch_route(['a.csv', 'b.csv'], 'json')
        self.assertTrue(validation.success, validation.error)
        self.assertEqual(validation.source, 'csv')
        self.assertEqual(validation.target, 'json')
        self.assertEqual(len(validation.files), 2)
        self.assertEqual(validation.capability.source, 'csv')

    def test_validate_batch_route_rejects_mixed_sources(self):
        validation = validate_batch_route(['a.csv', 'b.tsv'], 'json')
        self.assertFalse(validation.success)
        self.assertIn('同一种输入格式', validation.error)
        self.assertEqual({item.source for item in validation.files}, {'csv', 'tsv'})

    def test_convert_batch_files_runs_rows_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / 'a.csv'
            second = root / 'b.csv'
            first.write_text('name\nAda\n', encoding='utf-8')
            second.write_text('name\nBob\n', encoding='utf-8')

            result = convert_batch_files(
                [
                    BatchInput(filename='a.csv', source='csv', input_path=first),
                    BatchInput(filename='b.csv', source='csv', input_path=second),
                ],
                'json',
                root,
            )

        self.assertTrue(result['success'], result['logs'])
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['successCount'], 2)
        self.assertEqual(len(result['results']), 2)
        self.assertTrue(all(row['outputPath'] for row in result['results']))

class ConversionRobustnessRegressionTests(unittest.TestCase):
    def test_gif_to_png_outputs_frame_directory(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest('Pillow unavailable')
        from converters.pipeline import convert_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gif = root / 'anim.gif'
            frames = [Image.new('RGB', (8, 8), color) for color in ('red', 'green')]
            frames[0].save(gif, save_all=True, append_images=frames[1:], duration=50, loop=0)
            result = convert_file(gif, gif.name, 'gif', 'png', root / 'out')

            self.assertTrue(result.success, result.error)
            self.assertTrue(result.output_path.is_dir())
            self.assertTrue((result.output_path / 'frame_0001.png').is_file())
            self.assertEqual(result.validation.get('kind'), 'folder')

    def test_targz_validation_recognizes_tarball_not_plain_gz(self):
        import tarfile
        from converters.pipeline import convert_file

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'src'
            folder.mkdir()
            (folder / 'a.txt').write_text('ok', encoding='utf-8')
            result = convert_file(folder, folder.name, 'folder', 'tar.gz', root / 'out')

            self.assertTrue(result.success, result.error)
            self.assertTrue(tarfile.is_tarfile(result.output_path))
            self.assertEqual(result.validation.get('detectedFormat'), 'tar.gz')


if __name__ == '__main__':
    unittest.main()
