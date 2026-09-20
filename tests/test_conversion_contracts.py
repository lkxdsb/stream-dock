import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from converters.contracts import release_route_keys, release_status
from converters.models import ConversionLevel
from converters.registry import list_capabilities


class ConversionContractTests(unittest.TestCase):
    def test_release_gate_exactly_covers_152_registered_routes(self):
        routes = release_route_keys()
        registered = {capability.key for capability in list_capabilities()}
        self.assertEqual(len(routes), 152)
        self.assertLessEqual(routes, registered)
        self.assertTrue(all(capability.to_dict()['contract']['releaseGate'] == (capability.key in routes) for capability in list_capabilities()))
        self.assertTrue(all(not capability.to_dict()['contract']['releaseGate'] for capability in list_capabilities() if capability.level == ConversionLevel.VENDOR))

    def test_release_status_distinguishes_current_and_stale_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'release.json'
            report.write_text(json.dumps({
                'status': 'PASS', 'sourceRevision': 'abc', 'generatedAt': '2026-09-20T00:00:00Z',
                'evidence': {'matrix': {'path': '/private/local/report.json', 'routes': 152, 'passed': 152}}, 'failures': [],
            }), encoding='utf-8')
            with patch('converters.contracts._current_revision', return_value='abc'):
                current = release_status(report)
            with patch('converters.contracts._current_revision', return_value='def'):
                stale = release_status(report)

        self.assertEqual(current['status'], 'pass')
        self.assertTrue(current['current'])
        self.assertNotIn('path', current['evidence']['matrix'])
        self.assertEqual(stale['status'], 'stale')
        self.assertFalse(stale['current'])


if __name__ == '__main__':
    unittest.main()
