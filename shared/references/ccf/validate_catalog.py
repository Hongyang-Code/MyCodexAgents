"""Validate saved catalog structure and source file hash; not official authenticity."""
import collections,hashlib,json
from pathlib import Path

def validate():
    root=Path(__file__).parent;data=json.loads((root/'catalog-2026.json').read_text('utf-8'));entries=data['entries'];groups=collections.defaultdict(list)
    for e in entries:
        assert e['domain'] and e['full_name'] and e['kind'] in ['journal','conference'] and e['rank'] in ['A','B','C']
        assert 2<=e['page']<=72
        groups[e['domain'],e['kind'],e['rank']].append(e['number'])
    assert len(entries)==681 and len(groups)==60 and len({e['domain'] for e in entries})==10
    assert all(v==list(range(1,len(v)+1)) for v in groups.values())
    assert hashlib.sha256((root/'ccf-2026-source.pdf').read_bytes()).hexdigest()==data['source_sha256']
    print('PASS: 681 entries, 10 domains, 60 sequential groups, source hash matched. Official correction match remains pending.')
if __name__=='__main__':validate()
