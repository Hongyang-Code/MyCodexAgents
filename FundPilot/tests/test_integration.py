import tempfile
import unittest
from pathlib import Path
from fundpilot.__main__ import smoke

class IntegrationTests(unittest.TestCase):
    def test_smoke_not_production(self):
        with tempfile.TemporaryDirectory() as d:
            result=smoke(Path(d)/'new')
            self.assertTrue(result['test_only'])
            self.assertEqual(result['status'],'passed')
            self.assertEqual(result['notification_intents'],0)
            self.assertFalse(result['cloud_restore_verified'])
            self.assertFalse(result['real_prediction_validation'])
            with self.assertRaises(FileExistsError): smoke(Path(d)/'new')
