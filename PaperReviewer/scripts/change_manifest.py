"""Bind cumulative change explanations to exact UTF-8 source/final differences.

Line spans are zero-based half-open [start, end]; empty spans denote insertion
points. ``build`` returns an intentionally incomplete draft. Structural validity
never establishes scientific correctness of the supplied reasons.
"""
import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path

OPERATIONS = {
    'add': '增补', 'delete': '删除', 'replace': '替换', 'split': '拆句',
    'merge': '合并', 'reorder': '重排', 'limit_claim': '限定结论', 'format': '格式调整',
}


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _hunks(original_bytes, final_bytes):
    before = original_bytes.decode('utf-8').splitlines(keepends=True)
    after = final_bytes.decode('utf-8').splitlines(keepends=True)
    result = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag == 'equal':
            continue
        item = {'original_lines': [i, j], 'final_lines': [k, l],
                'before': ''.join(before[i:j]), 'after': ''.join(after[k:l])}
        fingerprint = _hash(json.dumps(item, ensure_ascii=False, sort_keys=True).encode('utf-8'))[:16]
        item['id'] = 'H' + fingerprint
        result.append(item)
    return result


def build(original_bytes, final_bytes):
    """Create a draft; callers must supply explanations before validation passes."""
    entries = []
    for index, hunk in enumerate(_hunks(original_bytes, final_bytes), 1):
        entries.append({'id': 'C%03d' % index, 'location': '', 'hunks': [hunk],
                        'operation': '', 'reason': '', 'meaning_impact': '', 'issue_ids': []})
    return {'schema_version': 1, 'original_sha256': _hash(original_bytes),
            'final_sha256': _hash(final_bytes), 'entries': entries,
            'no_changes_reason': ''}


def _explained(value):
    return (isinstance(value, str) and bool(value.strip())
            and '{{' not in value and value.strip().lower() not in {'todo', 'tbd', '待填写'})


def validate(original_bytes, final_bytes, manifest, known_issue_ids=None):
    """Check exact diff coverage; optionally require issue IDs from a run record."""
    errors = []
    if not isinstance(manifest, dict):
        return {'status': 'fail', 'errors': ['manifest must be an object']}
    if type(manifest.get('schema_version')) is not int or manifest.get('schema_version') != 1:
        errors.append('unsupported schema_version')
    for field, data in [('original_sha256', original_bytes), ('final_sha256', final_bytes)]:
        if manifest.get(field) != _hash(data):
            errors.append('stale or incorrect ' + field)
    try:
        expected = {h['id']: h for h in _hunks(original_bytes, final_bytes)}
    except (UnicodeError, AttributeError):
        return {'status': 'fail', 'errors': errors + ['source and final must be UTF-8 bytes']}
    entries = manifest.get('entries')
    if not isinstance(entries, list):
        return {'status': 'fail', 'errors': errors + ['entries must be a list']}
    if not expected:
        if entries:
            errors.append('no text differences but changes are claimed')
        if not _explained(manifest.get('no_changes_reason')):
            errors.append('unchanged text requires no_changes_reason')
    elif manifest.get('no_changes_reason'):
        errors.append('changed text cannot claim no changes')
    seen = []; entry_ids = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append('entry must be an object'); continue
        entry_id = entry.get('id')
        if not _explained(entry_id):
            errors.append('missing entry id')
        else:
            entry_ids.append(entry_id)
        for field in ['location', 'reason', 'meaning_impact']:
            if not _explained(entry.get(field)):
                errors.append(str(entry_id) + ': missing ' + field)
        if entry.get('operation') not in OPERATIONS:
            errors.append(str(entry_id) + ': invalid operation')
        issues = entry.get('issue_ids')
        if not isinstance(issues, list) or any(not _explained(x) for x in issues):
            errors.append(str(entry_id) + ': issue_ids must be a list of nonempty strings')
        elif len(set(issues)) != len(issues):
            errors.append(str(entry_id) + ': duplicate issue ids')
        elif known_issue_ids is not None and any(x not in known_issue_ids for x in issues):
            errors.append(str(entry_id) + ': unknown issue id')
        hunks = entry.get('hunks')
        if not isinstance(hunks, list) or not hunks:
            errors.append(str(entry_id) + ': missing hunks'); continue
        for hunk in hunks:
            if not isinstance(hunk, dict) or not isinstance(hunk.get('id'), str):
                errors.append(str(entry_id) + ': invalid hunk'); continue
            hid = hunk['id']; seen.append(hid)
            if hid not in expected:
                errors.append(str(entry_id) + ': invented or stale hunk ' + hid)
            elif hunk != expected[hid]:
                errors.append(str(entry_id) + ': hunk text or location differs from actual diff ' + hid)
    if len(entry_ids) != len(set(entry_ids)):
        errors.append('duplicate entry ids')
    if len(seen) != len(set(seen)):
        errors.append('hunk covered more than once')
    missing = sorted(set(expected) - set(seen))
    if missing:
        errors.append('unexplained hunks: ' + ', '.join(missing))
    return {'status': 'fail' if errors else 'pass', 'errors': errors,
            'change_entries': len(entries), 'diff_hunks': len(expected)}


def _quote_fragment(value):
    if not value:
        return '（空：此处为新增或删除的边界）\n'
    length = max([len(x) for x in re.findall(r'`+', value)] + [2]) + 1
    fence = '`' * length
    return fence + 'text\n' + value + ('' if value.endswith('\n') else '\n') + fence + '\n'


def _readable_lines(span):
    start, end = span
    if start == end:
        # A diff-only manifest cannot establish the total number of unchanged
        # trailing lines. Describe the boundary without guessing that it is EOF.
        return '第1行前（插入边界）' if start == 0 else '第' + str(start) + '行后（插入边界）'
    return '第' + str(start + 1) + '行' if end == start + 1 else '第' + str(start + 1) + '—' + str(end) + '行'


def render(manifest):
    """Render explanations first, keeping exact audit details collapsible."""
    lines = ['# 累计修改说明', '', '对照范围：原始稿 → 最终交付稿。', '']
    if not manifest['entries']:
        lines += ['本次未修改正文。', '', '原因：' + manifest.get('no_changes_reason', ''), '']
    for index, entry in enumerate(manifest['entries'], 1):
        lines += ['## 修改 ' + str(index), '', '- 修改位置：' + entry['location'], '',
                  '- 修改方式：' + OPERATIONS.get(entry['operation'], entry['operation']), '',
                  '**修改原因**', '', re.sub(r' (?=\d+\.\s)', '\n\n', entry['reason']), '',
                  '- 含义影响：' + entry['meaning_impact'], '',
                  '- 对应问题：' + ('、'.join(entry['issue_ids']) or '无问题 ID；依据见修改原因。'), '']
        for number, hunk in enumerate(entry['hunks'], 1):
            if len(entry['hunks']) > 1:
                lines += ['### 对照 ' + str(number), '']
            lines += ['原稿：' + _readable_lines(hunk['original_lines']) + '；终稿：' + _readable_lines(hunk['final_lines']) + '。', '',
                      '**修改前**', '', _quote_fragment(hunk['before']), '**修改后**', '', _quote_fragment(hunk['after']),
                      '<details><summary>差异定位记录</summary>', '',
                      '修改记录 ID：`' + entry['id'] + '`；差异块 ID：`' + hunk['id'] + '`。', '',
                      '机器行区间从 0 开始、左闭右开：原稿 ' + str(hunk['original_lines']) + '；终稿 ' + str(hunk['final_lines']) + '。', '',
                      '</details>', '']
            # Exact JSON makes line endings, trailing whitespace and final newline visible.
            for label, key in [('修改前', 'before'), ('修改后', 'after')]:
                lines += ['<details><summary>' + label + '精确文本（JSON 转义，显示空白）</summary>', '',
                          _quote_fragment(json.dumps(hunk[key], ensure_ascii=False)), '</details>', '']
    lines += ['<details><summary>原稿与终稿校验信息</summary>', '',
              '原始稿 SHA256：`' + manifest['original_sha256'] + '`', '',
              '最终稿 SHA256：`' + manifest['final_sha256'] + '`', '', '</details>', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ['draft', 'check', 'render']:
        sub = subs.add_parser(command)
        sub.add_argument('original'); sub.add_argument('final'); sub.add_argument('manifest')
        if command == 'check':
            sub.add_argument('--report', help='existing UTF-8 changes.md; must equal canonical render')
        if command == 'render':
            sub.add_argument('report')
    args = parser.parse_args()
    try:
        protected = {Path(args.original).resolve(), Path(args.final).resolve()}
        if args.command == 'draft' and Path(args.manifest).resolve() in protected:
            raise ValueError('manifest output must not overwrite original or final')
        if args.command == 'render' and Path(args.report).resolve() in protected | {Path(args.manifest).resolve()}:
            raise ValueError('report output must not overwrite original, final or manifest')
        original = Path(args.original).read_bytes(); final = Path(args.final).read_bytes()
        if args.command == 'draft':
            draft = build(original, final)
            Path(args.manifest).write_text(json.dumps(draft, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
            print(json.dumps({'status': 'draft', 'message': '解释尚未填写，不能宣称修改依据已核实。'}, ensure_ascii=False))
            return 0
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
        result = validate(original, final, manifest)
        if args.command == 'check' and args.report and result['status'] == 'pass':
            if Path(args.report).read_bytes() != render(manifest).encode('utf-8'):
                result['errors'].append('report differs from complete canonical change list')
                result['status'] = 'fail'
        if args.command == 'render' and result['status'] == 'pass':
            Path(args.report).write_bytes(render(manifest).encode('utf-8'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'pass' else 1
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'status': 'fail', 'errors': [str(exc)]}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
