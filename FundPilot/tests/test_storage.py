import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from fundpilot.storage import pack, restore, verify, sha256

class StorageTests(unittest.TestCase):
    def test_roundtrip_and_production_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root/'source'; source.mkdir()
            (source/'state.json').write_text('{"synthetic":true}')
            out=root/'bundle.zip'
            result=pack(source,out,run_id='test',test_only=True)
            with self.assertRaises(ValueError): verify(out,expected_sha=result['sha256'])
            restore(out,root/'restored',expected_sha=result['sha256'],allow_test=True)
            self.assertEqual((root/'restored/state.json').read_text(),'{"synthetic":true}')
            with self.assertRaises(FileExistsError): restore(out,root/'restored',expected_sha=result['sha256'],allow_test=True)
            with self.assertRaises(ValueError): verify(out,expected_sha='0'*64,allow_test=True)
    def test_traversal_and_unlisted_members(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ['../escape','/absolute','a\\b']:
                path=Path(d)/'bad.zip'
                with zipfile.ZipFile(path,'w') as z:
                    z.writestr('manifest.json','{}'); z.writestr(name,'bad')
                with self.assertRaises(ValueError): verify(path,expected_sha=sha256(path))
    def test_source_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source'; source.mkdir()
            (source/'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): pack(source,root/'x.zip',run_id='x',test_only=True)
    def test_unknown_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); s=root/'s';s.mkdir(); (s/'one').write_text('1')
            path=root/'z.zip';pack(s,path,run_id='x',test_only=False)
            with zipfile.ZipFile(path,'a') as z: z.writestr('extra','2')
            with self.assertRaises(ValueError): verify(path,expected_sha=sha256(path))
