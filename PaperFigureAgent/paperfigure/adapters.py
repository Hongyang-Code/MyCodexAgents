import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from .storage import digest, read_json, write_json


def discover_drawio(explicit=None):
    candidates=[explicit,os.environ.get('DRAWIO_BIN'),shutil.which('drawio'),shutil.which('draw.io')]
    receipt=Path(__file__).resolve().parents[1]/'.cache/drawio/runtime.json'
    if receipt.exists():candidates.append(read_json(receipt).get('executable'))
    if os.name=='nt':
        for key in ('ProgramFiles','LOCALAPPDATA'):
            if os.environ.get(key):candidates.append(str(Path(os.environ[key])/'draw.io/draw.io.exe'))
    elif os.sys.platform=='darwin':candidates.append('/Applications/draw.io.app/Contents/MacOS/draw.io')
    return next((str(Path(c).resolve()) for c in candidates if c and Path(c).is_file()),None)


def capabilities():
    return {'python':os.sys.version.split()[0], 'drawio':discover_drawio(),
            'pdf_text':bool(importlib.util.find_spec('pypdf')), 'image_metadata':bool(importlib.util.find_spec('PIL')),
            'host_semantics':'requires current host AI; no autonomous model API configured',
            'host_vision':'probe with actual image tool in current host',
            'host_browse':'probe current host tools', 'image_generation':'optional; not needed for native figures',
            'interactive_edit':'not_run until actual editor interaction', 'standalone_model':'not_configured'}


def render(source,output,executable=None,page=0,fmt='png',timeout=55):
    source=Path(source).resolve();output=Path(output).resolve();exe=discover_drawio(executable)
    if not exe:return {'status':'not_run','reason':'Native draw.io unavailable; set DRAWIO_BIN or use official browser editor','figure_sha256':digest(source)}
    if fmt not in ('png','svg','pdf'):raise ValueError('Unsupported export format')
    if output.exists():raise ValueError('Render to a new file; stale outputs must not be mistaken for new exports')
    output.parent.mkdir(parents=True,exist_ok=True)
    # Separate Electron profile prevents touching the user's draw.io settings/session.
    with tempfile.TemporaryDirectory(prefix='pfa-native-') as profile:
        # draw.io >=27.0.2 CLI is one-based; public Python API stays zero-based.
        page_base=int(os.environ.get('DRAWIO_PAGE_BASE','1'))
        cmd=[exe,'--export','--format',fmt,'--page-index',str(page+page_base),'--output',str(output),'--border','10','--disable-update',
             '--user-data-dir='+profile,str(source)]
        if fmt=='png':cmd[1:1]=['--scale','2']
        if fmt=='pdf':cmd[1:1]=['--crop']
        env=dict(os.environ,DRAWIO_DISABLE_UPDATE='true')
        options={}
        if os.name=='nt':
            startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
            options={'startupinfo':startup,'creationflags':subprocess.CREATE_NO_WINDOW}
        try:
            result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,env=env,**options)
            ok=result.returncode==0 and output.is_file() and output.stat().st_size>0
            detail=(result.stdout+result.stderr).decode('utf-8',errors='replace')[-1500:]
        except subprocess.TimeoutExpired:
            ok=False;detail='Native renderer timed out'
    signature=output.read_bytes()[:200] if output.exists() else b''
    valid=(signature.startswith(b'\x89PNG') if fmt=='png' else signature.startswith(b'%PDF') if fmt=='pdf' else b'<svg' in output.read_bytes()[:1500] if output.exists() else False)
    return {'status':'pass' if ok and valid else 'fail','renderer':'draw.io Desktop','executable':exe,'format':fmt,'page':page,
            'figure_sha256':digest(source),'output':str(output),'output_sha256':digest(output) if output.exists() else None,'log':detail}
