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


if __name__ == '__main__':
    unittest.main()
