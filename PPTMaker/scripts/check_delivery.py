"""Validate review evidence and hashes; cannot verify human/agent judgments."""
import argparse
import importlib.util
import json
import re
from pathlib import Path
import check_deck

ROOT = Path(__file__).resolve().parents[2]
DESIGN_PAGE_DIMENSIONS = ('composition', 'hierarchy', 'color', 'typography', 'visual_expression', 'alignment')
DESIGN_DECK_DIMENSIONS = ('consistency', 'rhythm', 'reference_fit')
spec = importlib.util.spec_from_file_location('text_format', ROOT/'TextReadable/scripts/check_format.py')
text_format = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_format)


def validate_design(review, slide_ids, pptx_hash, previews):
    """Require review coverage and evidence, not an automated aesthetic score."""
    errors = []

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def dimensions(items, keys, scope):
        for key in keys:
            item = items.get(key, {})
            if item.get('status') != 'pass' or not nonempty(item.get('evidence')):
                errors.append('incomplete design dimension: '+scope+'/'+key)

    if review.get('status') != 'pass' or review.get('pptx_sha256') != pptx_hash:
        errors.append('design review missing, failed or stale')
    references = review.get('references', [])
    if not references:
        errors.append('design review requires viewed references or template')
    for ref in references:
        if ref.get('kind') not in ('reference', 'template') or ref.get('viewed') is not True:
            errors.append('design reference not actually viewed')
        for key in ('source', 'pages', 'adopt', 'avoid'):
            if not nonempty(ref.get(key)):
                errors.append('incomplete design reference: '+key)
    pages = review.get('slides', [])
    if [page.get('id') for page in pages] != slide_ids:
        errors.append('design review must cover all final slides in order')
    images = {page.get('id'): page.get('image') for page in previews}
    for page in pages:
        if page.get('status') != 'pass' or not page.get('image') or page.get('image') != images.get(page.get('id')):
            errors.append('design page failed or bound to a different preview')
        dimensions(page.get('dimensions', {}), DESIGN_PAGE_DIMENSIONS, str(page.get('id')))
    dimensions(review.get('whole_deck', {}), DESIGN_DECK_DIMENSIONS, 'whole_deck')
    issues = review.get('issues')
    if not isinstance(issues, list):
        errors.append('design issues must be an explicit list')
    else:
        ids = [issue.get('id') for issue in issues]
        if any(not nonempty(i) for i in ids) or len(ids) != len(set(ids)):
            errors.append('design issue IDs missing or duplicated')
        for issue in issues:
            if issue.get('status') not in ('resolved', 'rejected') or issue.get('scope') not in ['whole_deck'] + slide_ids:
                errors.append('unresolved or invalid design issue')
            for key in ('finding', 'impact', 'action', 'recheck'):
                if not nonempty(issue.get(key)):
                    errors.append('incomplete design issue: '+key)
    feedback = review.get('user_style_feedback', {})
    if feedback.get('state') not in ('pending', 'accepted'):
        errors.append('user style feedback missing or rejected')
    if not nonempty(feedback.get('evidence')):
        errors.append('user style feedback requires honest context')
    return errors


def validate(record, base):
    errors = []
    base = Path(base).resolve()

    def artifact(item):
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('artifact requires path and sha256')
        path = (base/item['path']).resolve()
        if not path.is_relative_to(base):
            raise ValueError('artifact outside run directory')
        if not path.is_file() or check_deck.digest(path) != item.get('sha256'):
            raise ValueError('missing or stale artifact: '+item['path'])
        return path

    try:
        if record.get('schema_version') != 1:
            raise ValueError('review schema_version must be 1')
        if record.get('mode') not in ('template', 'materials', 'topic'):
            errors.append('invalid mode')
        if record.get('interaction') not in ('collaborative', 'direct'):
            errors.append('invalid interaction')
        approval = record.get('approval', {})
        needed = 'confirmed' if record.get('interaction') == 'collaborative' else 'direct_authorized'
        if approval.get('state') != needed or not approval.get('evidence'):
            errors.append('missing representative-slide approval or direct authorization')
        pptx = artifact(record['pptx'])
        receipt = json.loads(artifact(record['finalizer']).read_text(encoding='utf-8'))
        if receipt.get('finalSha256') != check_deck.digest(pptx):
            errors.append('finalizer bound to a different PPTX')
        if receipt.get('packageIntegrity', {}).get('status') != 'pass' or receipt.get('presentationLayout', {}).get('exitCode') != 0 or receipt.get('firstPartyImport', {}).get('passed') is not True:
            errors.append('missing/failed packaged finalizer checks')
        req_path = artifact(record['requirements'])
        req = json.loads(req_path.read_text(encoding='utf-8'))
        deck_result = check_deck.check(pptx, req)
        errors += deck_result['errors']
        if deck_result.get('warnings') and not record.get('warning_dispositions'):
            errors.append('layout warnings require explicit disposition')
        vr = record.get('visual_revision_rounds')
        if type(vr) is not int or not 0 <= vr <= 3:
            errors.append('visual revision budget exceeded/invalid')
        batches = record.get('text_batches', [])
        if not 1 <= len(batches) <= 2:
            errors.append('TextReadable batch count must be 1..2')
        for batch in batches:
            rounds = batch.get('revision_rounds')
            if type(rounds) is not int or not 0 <= rounds <= 3:
                errors.append('TextReadable revision budget exceeded/invalid')
            original = artifact(batch['original'])
            final = artifact(batch['final'])
            contract = artifact(batch['requirements'])
            tr = json.loads(artifact(batch['result']).read_text(encoding='utf-8'))
            required = ('readability', 'wording_rigor', 'semantic_fidelity', 'coverage', 'content_requirements', 'format_requirements')
            if tr.get('status') != 'passed' or any(tr.get('checks', {}).get(k) != 'pass' for k in required):
                errors.append('TextReadable incomplete or failed')
            if tr.get('revision_rounds') != rounds or tr.get('validated_text_sha256') != check_deck.digest(final):
                errors.append('TextReadable revision/hash mismatch')
            if tr.get('original_sha256') != check_deck.digest(original):
                errors.append('TextReadable original baseline mismatch')
            rules = json.loads(contract.read_text(encoding='utf-8'))
            fr = text_format.validate(final.read_text(encoding='utf-8'), rules)
            if fr['status'] != 'pass':
                errors.extend(fr['errors'] or ['TextReadable format requirements missing'])
            expected = {v['id'] for v in rules.get('content', [])}
            results = tr.get('requirement_results', [])
            actual = [v.get('id') for v in results]
            if not expected or set(actual) != expected or len(actual) != len(set(actual)) or any(v.get('status') != 'pass' or not v.get('evidence') for v in results):
                errors.append('missing/failed substantive requirement review')
        if batches and record.get('copy_sha256') != batches[-1]['final']['sha256']:
            errors.append('deck copy not bound to final reviewed text')
        if batches:
            headings = [s.get('heading', '') for s in rules.get('format', {}).get('sections', [])]
            reviewed_ids = [m.group(1) for h in headings if (m := re.match(r'^### \[(S[0-9]+)\] ', h))]
            if reviewed_ids != [s['id'] for s in req['slides']]:
                errors.append('last TextReadable batch must cover all final slides in order')
        checks = record.get('checks', {})
        for key in ('facts', 'coverage', 'narrative', 'copy_to_deck', 'editability', 'visual', 'design'):
            item = checks.get(key, {})
            if item.get('status') != 'pass' or not item.get('evidence'):
                errors.append('incomplete substantive check: '+key)
        if record.get('mode') == 'template':
            item = checks.get('template', {})
            if item.get('status') != 'pass' or not item.get('evidence'):
                errors.append('missing template comparison')
            artifact(record['changes'])
        if record.get('mode') == 'topic':
            artifact(record['sources'])
        previews = record.get('slides_reviewed', [])
        ids = [s.get('id') for s in previews]
        if ids != [s['id'] for s in req['slides']]:
            errors.append('not all final slides reviewed in order')
        for slide in previews:
            artifact(slide['image'])
            if slide.get('status') != 'pass' or not slide.get('evidence') or slide.get('pptx_sha256') != record['pptx']['sha256']:
                errors.append('unreviewed or stale slide preview')
        errors += validate_design(record.get('design_review', {}), [s['id'] for s in req['slides']], record['pptx']['sha256'], previews)
        if record.get('unresolved'):
            errors.append('unresolved items prevent final delivery')
        audience = record.get('audience_review', {})
        if audience.get('status') != 'pass':
            errors.append('strict audience review missing or not passed')
        for key in ('target_audience', 'reviewer_profile', 'basis'):
            if not isinstance(audience.get(key), str) or not audience[key].strip():
                errors.append('missing audience review context: '+key)
        if audience.get('pptx_sha256') != record['pptx']['sha256'] or audience.get('copy_sha256') != record.get('copy_sha256'):
            errors.append('strict audience review bound to old PPTX or copy')
        rounds = audience.get('revision_rounds')
        if type(rounds) is not int or not 0 <= rounds <= 3:
            errors.append('strict audience revision budget exceeded/invalid')
        for key in ('evidence', 'reasoning', 'comparisons', 'communication', 'purpose'):
            item = audience.get('dimensions', {}).get(key, {})
            if item.get('status') != 'pass' or not item.get('evidence'):
                errors.append('incomplete strict audience dimension: '+key)
        pages = audience.get('slides', [])
        if [s.get('id') for s in pages] != [s['id'] for s in req['slides']]:
            errors.append('strict audience review must cover all final slides in order')
        for page in pages:
            if page.get('status') != 'pass' or not page.get('question') or not page.get('evidence'):
                errors.append('missing substantive strict audience page review')
        issues = audience.get('issues')
        if not isinstance(issues, list):
            errors.append('strict audience issues must be an explicit list')
        else:
            issue_ids = [i.get('id') for i in issues]
            if any(not i for i in issue_ids) or len(set(issue_ids)) != len(issue_ids):
                errors.append('strict audience issue IDs missing or duplicated')
            for issue in issues:
                if issue.get('status') not in ('resolved', 'rejected'):
                    errors.append('unresolved strict audience issue')
                if issue.get('scope') not in ['whole_deck'] + [s['id'] for s in req['slides']]:
                    errors.append('invalid strict audience issue scope')
                for key in ('question', 'evidence', 'impact', 'severity', 'decision', 'action', 'recheck'):
                    if not isinstance(issue.get(key), str) or not issue[key].strip():
                        errors.append('incomplete strict audience issue: '+key)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
    return {'status': 'fail' if errors else 'pass', 'errors': errors,
            'scope': 'record consistency, file structure and hashes only; not proof of facts or visual quality'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review')
    args = parser.parse_args()
    p = Path(args.review)
    try:
        result = validate(json.loads(p.read_text(encoding='utf-8-sig')), p.parent)
    except (OSError, ValueError) as exc:
        result = {'status': 'fail', 'errors': [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result['status'] != 'pass')


if __name__ == '__main__':
    raise SystemExit(main())
