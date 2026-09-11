"""Exact change coverage tests; semantic explanations still require human review."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'change_manifest.py'
spec = importlib.util.spec_from_file_location('change_manifest', SCRIPT)
changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changes)


def explained(before, after, operation='replace'):
    manifest = changes.build(before, after)
    for entry in manifest['entries']:
        entry.update(location='第1节，对照所列原文', operation=operation,
                     reason='依据问题 Q1 修正范围；这里只测试记录，不验证学术判断。',
                     meaning_impact='将结论限定为给定数据集；数值不变。', issue_ids=['Q1'])
    if not manifest['entries']:
        manifest['no_changes_reason'] = '复查后无需修改。'
    return manifest


class ChangeManifestTests(unittest.TestCase):
    def test_draft_is_not_verified(self):
        self.assertEqual(changes.validate(b'a', b'b', changes.build(b'a', b'b'))['status'], 'fail')

    def test_add_delete_and_sentence_rewrite(self):
        for before, after, op in [(b'a\n', b'a\nb\n', 'add'), (b'a\nb\n', b'a\n', 'delete'),
                                  ('该模型可以处理全部图像。'.encode(), '该模型在本数据集上有效。'.encode(), 'replace')]:
            with self.subTest(operation=op):
                self.assertEqual(changes.validate(before, after, explained(before, after, op))['status'], 'pass')

    def test_move_covers_both_boundaries(self):
        before = b'A\nB\nC\n'; after = b'B\nC\nA\n'
        manifest = explained(before, after, 'reorder')
        self.assertEqual(len(manifest['entries']), 2)
        first = manifest['entries'][0]
        first['hunks'] += manifest['entries'][1]['hunks']; manifest['entries'] = [first]
        first['location'] = '原第1行移动到终稿第3行，两处差异见下。'
        self.assertEqual(changes.validate(before, after, manifest)['status'], 'pass')

    def test_limit_claim_and_punctuation(self):
        for before, after, op in [('对所有场景有效。', '对已测试的场景有效。', 'limit_claim'),
                                  ('结果有效,但边界未测。', '结果有效，但边界未测。', 'format')]:
            source = before.encode(); final = after.encode()
            self.assertEqual(changes.validate(source, final, explained(source, final, op))['status'], 'pass')

    def test_line_endings_and_trailing_spaces_are_changes(self):
        for source, final in [(b'A\r\n', b'A\n'), (b'A \n', b'A\n'), (b'A', b'A\n')]:
            with self.subTest(source=source):
                manifest = explained(source, final, 'format')
                self.assertEqual(changes.validate(source, final, manifest)['diff_hunks'], 1)
                self.assertEqual(manifest['entries'][0]['hunks'][0]['before'], source.decode())
                self.assertNotEqual(manifest['original_sha256'], manifest['final_sha256'])

    def test_omission_and_double_coverage(self):
        source = b'A\nkeep\nB\n'; final = b'C\nkeep\nD\n'
        manifest = explained(source, final)
        omitted = copy.deepcopy(manifest); omitted['entries'].pop()
        self.assertEqual(changes.validate(source, final, omitted)['status'], 'fail')
        repeated = copy.deepcopy(manifest); repeated['entries'][0]['hunks'].append(repeated['entries'][1]['hunks'][0])
        self.assertEqual(changes.validate(source, final, repeated)['status'], 'fail')

    def test_fabricated_before_after_or_location(self):
        for field, value in [('before', 'wrong'), ('after', 'wrong'), ('original_lines', [2, 3]), ('final_lines', [2, 3])]:
            manifest = explained(b'A', b'B'); manifest['entries'][0]['hunks'][0][field] = value
            with self.subTest(field=field):
                self.assertEqual(changes.validate(b'A', b'B', manifest)['status'], 'fail')

    def test_stale_hash_and_stale_final(self):
        manifest = explained(b'A', b'B')
        self.assertEqual(changes.validate(b'A', b'C', manifest)['status'], 'fail')
        manifest['original_sha256'] = '0' * 64
        self.assertEqual(changes.validate(b'A', b'B', manifest)['status'], 'fail')

    def test_unchanged_cannot_claim_modification(self):
        manifest = explained(b'A', b'B')
        manifest['final_sha256'] = manifest['original_sha256']
        self.assertEqual(changes.validate(b'A', b'A', manifest)['status'], 'fail')
        self.assertEqual(changes.validate(b'A', b'A', explained(b'A', b'A'))['status'], 'pass')
        self.assertEqual(changes.validate(b'A', b'A', changes.build(b'A', b'A'))['status'], 'fail')

    def test_cumulative_reversion_excludes_intermediate(self):
        original = b'A\nB\n'; middle = b'X\nY\n'; final = b'A\nZ\n'
        cumulative = explained(original, final)
        self.assertEqual(cumulative['entries'][0]['hunks'][0]['before'], 'B\n')
        self.assertEqual(cumulative['entries'][0]['hunks'][0]['after'], 'Z\n')
        self.assertNotIn('X', str(cumulative))
        self.assertEqual(changes.validate(original, final, explained(middle, final))['status'], 'fail')
        restored = explained(original, original)
        self.assertEqual(restored['entries'], [])

    def test_final_language_edit_requires_new_manifest(self):
        original = b'Claim.\n'; content = b'Limited claim.\n'; final = b'Limited claim!\n'
        self.assertEqual(changes.validate(original, final, explained(original, content))['status'], 'fail')
        self.assertEqual(changes.validate(original, final, explained(original, final))['status'], 'pass')

    def test_required_explanations_and_known_issue_ids(self):
        for field in ['location', 'reason', 'meaning_impact', 'operation']:
            manifest = explained(b'A', b'B'); manifest['entries'][0][field] = ''
            self.assertEqual(changes.validate(b'A', b'B', manifest)['status'], 'fail')
        manifest = explained(b'A', b'B')
        self.assertEqual(changes.validate(b'A', b'B', manifest, {'Q2'})['status'], 'fail')
        self.assertEqual(changes.validate(b'A', b'B', manifest, {'Q1'})['status'], 'pass')

    def test_grouped_mechanical_edits_preserve_all_fragments(self):
        source = b'a,\nkeep\nb,\n'; final = b'a;\nkeep\nb;\n'
        manifest = explained(source, final, 'format')
        manifest['entries'][0]['hunks'] += manifest['entries'][1]['hunks']
        manifest['entries'] = manifest['entries'][:1]
        manifest['entries'][0]['location'] = '第1、3行，精确范围见各差异块。'
        self.assertEqual(changes.validate(source, final, manifest)['status'], 'pass')
        rendered = changes.render(manifest)
        self.assertIn('a,', rendered); self.assertIn('b,', rendered)

    def test_invalid_objects_fail_without_crashing(self):
        for manifest in [None, {}, {'schema_version': 1, 'entries': [None]}]:
            self.assertEqual(changes.validate(b'A', b'B', manifest)['status'], 'fail')
        bad_utf8 = changes.build(b'A', b'B')
        self.assertEqual(changes.validate(b'\xff', b'B', bad_utf8)['status'], 'fail')

    def test_stable_hunks_and_render_escaped_whitespace(self):
        source = b'A\r\n'; final = b'A\n'
        self.assertEqual(changes.build(source, final), changes.build(source, final))
        rendered = changes.render(explained(source, final, 'format'))
        self.assertIn('\\r\\n', rendered); self.assertIn('\\n', rendered)
        self.assertIn('本次未修改正文', changes.render(explained(b'A', b'A')))

    def test_render_prioritizes_readable_locations(self):
        import re
        manifest = explained(b'A\nB\n', b'C\nD\n')
        rendered = changes.render(manifest)
        visible = re.sub(r'<details>.*?</details>', '', rendered, flags=re.S)
        self.assertIn('原稿：第1—2行；终稿：第1—2行', visible)
        self.assertIn('修改位置', visible)
        self.assertNotIn('SHA256', visible)
        self.assertNotIn(manifest['entries'][0]['hunks'][0]['id'], visible)
        self.assertNotIn('[0, 2]', visible)
        self.assertEqual(changes._readable_lines([0, 0]), '第1行前（插入边界）')
        self.assertEqual(changes._readable_lines([2, 2]), '第2行后（插入边界）')
        self.assertEqual(changes._readable_lines([1, 2]), '第2行')

    def test_cli_cannot_overwrite_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'original.md'; final = root / 'final.md'
            source.write_bytes(b'A'); final.write_bytes(b'B')
            result = subprocess.run([sys.executable, str(SCRIPT), 'draft', str(source), str(final), str(source)], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(source.read_bytes(), b'A')

    def test_cli_report_must_match_manifest(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'original.md'; final = root / 'final.md'
            manifest = root / 'changes.json'; report = root / 'changes.md'
            source.write_bytes(b'A'); final.write_bytes(b'B')
            manifest.write_text(json.dumps(explained(b'A', b'B'), ensure_ascii=False), encoding='utf-8')
            base = [sys.executable, str(SCRIPT)]
            rendered = subprocess.run(base + ['render', str(source), str(final), str(manifest), str(report)], capture_output=True)
            self.assertEqual(rendered.returncode, 0, rendered.stdout)
            checked = subprocess.run(base + ['check', str(source), str(final), str(manifest), '--report', str(report)], capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stdout)
            report.write_text('incomplete report', encoding='utf-8')
            failed = subprocess.run(base + ['check', str(source), str(final), str(manifest), '--report', str(report)], capture_output=True)
            self.assertEqual(failed.returncode, 1)


if __name__ == '__main__':
    unittest.main()
