"""Check proposed FundPilot public files for obvious private-artifact mistakes.

Not a full secret detector. Always review git diff manually before publishing.
"""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','FundPilot'],cwd=root,text=True).splitlines()
for name in files:
    p=Path(name)
    if any(part in {'inputs','outputs','state','.cache'} for part in p.parts) or p.suffix in {'.sqlite','.db','.zip','.png','.jpg','.pdf'}:
        sys.exit('Refuse private artifact in public candidate: '+name)
    body=(root/p).read_text(encoding='utf-8')
    if any(token in body for token in ['lib'+'file_', 'Calpico'+'File_', 'BEGIN '+'PRIVATE KEY', 'gh'+'p_', 'sk-'+'proj-']):
        sys.exit('Refuse possible private identifier/secret in '+name)
print(f'PASS: {len(files)} FundPilot text files; manual review still required')
