"""Private SQLite operation reservations; no tool execution or token metering.

A caller must explicitly seed a single shared ledger from reviewed complete run
usage. None stays unknown. Creation never replaces a ledger. Reservations commit
before actions, remain consumed on failure/crash, and never authorize replay.
"""
from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from urllib.parse import quote

LIMITS = {'source':12, 'retry':1, 'llm':12, 'prediction_batch':1}


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def aware(value):
    t=datetime.fromisoformat(value)
    if t.tzinfo is None:raise ValueError('timezone required')
    return t


class DurableBudget:
    def __init__(self,path):
        if '..' in Path(path).parts:raise ValueError('parent traversal rejected')
        self.path=Path(os.path.abspath(path))

    @classmethod
    def create(cls,path,*,run_id,used,candidate_history):
        from .upstream_bridge import write_bytes_new
        if not isinstance(run_id,str) or not run_id.strip():raise ValueError('run identity required')
        if set(used)!=set(LIMITS):raise ValueError('all usage fields explicit; unknown is None')
        if any(v is not None and (type(v) is not int or v<0) for v in used.values()):
            raise ValueError('nonnegative actual operation counts or unknown required')
        if candidate_history is not None:
            if not isinstance(candidate_history,list):raise ValueError('complete candidate history or None required')
            for r in candidate_history:
                if r.get('counts_toward_next_7_day_change_budget') is True or 'frozen_at' in r:
                    aware(r.get('attempted_at',r.get('frozen_at')))
        seed={'ledger_id':str(uuid.uuid4()),'run_id':run_id,'used':used,'candidate_history':candidate_history,'limits':LIMITS}
        state={'schema':1,'seed':seed,'stopped':False,'stop_reason':None,'operations':[]}
        # Exclusive creation; interrupted initialization is deliberately unusable.
        write_bytes_new(path,b'')
        b=cls(path)
        with b.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, sha256 TEXT NOT NULL)')
            body=encoded(state)
            c.execute('INSERT INTO state VALUES(1,?,?)',(body,hashlib.sha256(body.encode()).hexdigest()))
            c.commit()
        return b

    @contextmanager
    def connection(self):
        from .upstream_bridge import private_parent,check_file
        with private_parent(self.path) as (parent,name):
            fd=os.open(name,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                check_file(fd);s=os.fstat(fd)
                if s.st_mode&0o600!=0o600:raise ValueError('writable private ledger required')
                # Reject unsafe pre-existing SQLite journals as well as the DB.
                for suffix in ('-journal','-wal','-shm'):
                    try:j=os.open(name+suffix,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                    except FileNotFoundError:continue
                    try:check_file(j)
                    finally:os.close(j)
                old=os.umask(0o077)
                try:
                    quoted_name = quote(name, safe='')
                    database_uri = f'file:/proc/self/fd/{parent}/{quoted_name}?mode=rw'
                    with closing(sqlite3.connect(database_uri,uri=True,timeout=10)) as c:
                        st=os.stat(name,dir_fd=parent,follow_symlinks=False)
                        if (st.st_dev,st.st_ino)!=(s.st_dev,s.st_ino):raise ValueError('ledger replaced during open')
                        c.execute('PRAGMA synchronous=FULL')
                        try:yield c
                        except BaseException:c.rollback();raise
                finally:os.umask(old)
            finally:os.close(fd)

    def _read(self,c):
        if c.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('corrupt ledger')
        rows=c.execute('SELECT body,sha256 FROM state WHERE id=1').fetchall()
        if len(rows)!=1:raise ValueError('missing ledger state')
        body,sha=rows[0]
        if hashlib.sha256(body.encode()).hexdigest()!=sha:raise ValueError('ledger checksum mismatch')
        d=json.loads(body)
        if d.get('schema')!=1 or d['seed']['limits']!=LIMITS or not isinstance(d['operations'],list):
            raise ValueError('unsupported ledger state')
        return d

    def _write(self,c,d):
        body=encoded(d);c.execute('UPDATE state SET body=?,sha256=? WHERE id=1',
                                (body,hashlib.sha256(body.encode()).hexdigest()));c.commit()

    def snapshot(self):
        with self.connection() as c:return self._read(c)

    def stop(self,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('stop reason required')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE');d=self._read(c)
            d['stopped']=True;d['stop_reason']=reason;self._write(c,d)

    def require_known(self,*kinds):
        d=self.snapshot()
        if d['stopped']:raise ValueError('budget stopped')
        if any(d['seed']['used'].get(k) is None for k in kinds):raise ValueError('prior usage unknown')

    def reserve(self,operation_id,kind,*,parent=None,failure=None,payload=None):
        if not isinstance(operation_id,str) or not operation_id.strip():raise ValueError('operation ID required')
        if kind not in (*LIMITS,'candidate','evaluation','checkpoint_resume','comparison_arm','diagnostic_evaluation'):raise ValueError('unsupported operation')
        ph=hashlib.sha256(encoded(payload).encode()).hexdigest()
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE');d=self._read(c)
            if d['stopped']:return 'stop'
            ops=d['operations']
            prior=next((o for o in ops if o['id']==operation_id),None)
            if prior:
                if (prior['kind'],prior['parent'],prior['payload_sha256'])!=(kind,parent,ph):
                    raise ValueError('operation ID reused with different arguments')
                return 'already_reserved_do_not_execute'
            count=lambda k:sum(o['kind']==k for o in ops)
            grant=d['seed'].get('diagnostic_grant')
            trend_grant=bool(grant and grant.get('grant_kind')=='trend_diagnostic')
            allowed_grant_kinds=(('prediction_batch','llm','checkpoint_resume','source','retry',
                                  'diagnostic_evaluation') if trend_grant else
                                 ('prediction_batch','comparison_arm','llm','checkpoint_resume',
                                  'diagnostic_evaluation'))
            if grant and kind not in allowed_grant_kinds:
                return 'skip_partial'
            used=d['seed']['used']
            allowed=True
            if kind in LIMITS:
                keys=('source','retry') if kind in ('source','retry') else (kind,)
                if any(used[k] is None for k in keys):raise ValueError('prior usage unknown')
                if kind in ('source','retry'):
                    allowed=sum(used[k]+count(k) for k in keys)<LIMITS['source']
                    if kind=='retry':
                        allowed=(allowed and used['retry']+count('retry')<1 and failure=='transient'
                                 and any(o['id']==parent and o['kind']=='source' for o in ops))
                    elif parent is not None:allowed=False
                else:allowed=used[kind]+count(kind)<LIMITS[kind] and parent is None
            if kind=='candidate':
                hist=d['seed']['candidate_history']
                if hist is None:raise ValueError('complete candidate history required')
                t=datetime.now(timezone.utc)
                dates=[aware(r.get('attempted_at',r.get('frozen_at'))) for r in hist
                       if r.get('counts_toward_next_7_day_change_budget') is True or 'frozen_at' in r]
                dates += [aware(o['at']) for o in ops if o['kind']=='candidate']
                allowed=parent is None and all(t-old>=timedelta(days=7) for old in dates)
            if kind=='evaluation':
                allowed=(any(o['id']==parent and o['kind']=='candidate' for o in ops)
                         and not any(o['kind']=='evaluation' and o['parent']==parent for o in ops))
            if kind=='comparison_arm':
                allowed=(any(o['id']==parent and o['kind']=='prediction_batch' for o in ops)
                         and not any(o['kind']=='comparison_arm' and o['parent']==parent for o in ops)
                         and used['llm'] is not None and used['llm']+count('llm')<=3)
            if kind=='diagnostic_evaluation':
                requests={o['id'] for o in ops if o['kind']=='llm'}
                completed={o['parent'] for o in ops if o['kind']=='checkpoint_resume'}
                responses_ready=(bool(requests) and requests<=completed) if trend_grant else (
                    len(requests)==12 and len(completed)==12)
                allowed=(bool(grant) and responses_ready and count('diagnostic_evaluation')==0
                         and any(o['id']==parent and o['kind']=='prediction_batch' for o in ops))
            if kind=='checkpoint_resume':
                allowed=any(o['id']==parent and o['kind']=='llm' for o in ops)
            if not allowed:return 'skip_partial'
            # No release method: failure and uncertain crash outcomes keep charges.
            ops.append({'id':operation_id,'kind':kind,'parent':parent,'payload_sha256':ph,
                        'at':datetime.now(timezone.utc).isoformat()})
            self._write(c,d)
            return 'reserved'

    def require(self,*args,**kwargs):
        status=self.reserve(*args,**kwargs)
        if status!='reserved':raise ValueError('operation not authorized: '+status)

    def run_source_attempt(self,operation_id,action,*,payload=None):
        """Commit one source charge before one callback invocation.

        The caller must guarantee that the callback performs at most one source
        request.  This cannot intercept extra I/O inside the callback or host
        tools invoked outside this process.
        """
        if not callable(action):raise ValueError('source action must be callable')
        self.require(operation_id,'source',payload=payload)
        return action()
