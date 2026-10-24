"""Synthetic multi-process reservations, never model/source requests."""
import json
import os
from pathlib import Path
from datetime import datetime,timezone,timedelta
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from fundpilot.durable_budget import DurableBudget

USED = dict(source=0, retry=0, llm=0, prediction_batch=0)


class DurableBudgetTests(unittest.TestCase):
    def make(self, td, **changes):
        path=Path(td)/'budget.sqlite'
        DurableBudget.create(path, run_id='synthetic-run', used=changes.pop('used', USED),
                             candidate_history=changes.pop('history', []), **changes)
        return DurableBudget(path)

    def processes(self, path, ids):
        code='''import json,sys
from fundpilot.durable_budget import DurableBudget
try:
 print(json.dumps({'status':DurableBudget(sys.argv[1]).reserve(sys.argv[2],'source')}))
except (ValueError,OSError) as e:
 print(json.dumps({'error':str(e)}))
'''
        ps=[subprocess.Popen([sys.executable,'-c',code,str(path),i],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in ids]
        result=[]
        for p in ps:
            out,err=p.communicate(timeout=30);self.assertEqual(p.returncode,0,err);result.append(json.loads(out))
        return result

    def test_thirteen_processes_same_id_once_and_global_twelve_limit(self):
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td)
            r=self.processes(b.path,['same']*13)
            self.assertEqual(sum(x.get('status')=='reserved' for x in r),1)
            self.assertEqual(sum(x.get('status')=='already_reserved_do_not_execute' for x in r),12)
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td);r=self.processes(b.path,[str(i) for i in range(13)])
            self.assertEqual(sum(x.get('status')=='reserved' for x in r),12)
            self.assertEqual(sum(x.get('status')=='skip_partial' for x in r),1)
            self.assertEqual(len(b.snapshot()['operations']),12)

    def test_crash_after_reservation_keeps_consumption_and_stop_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td)
            code="from fundpilot.durable_budget import DurableBudget;import sys,os;DurableBudget(sys.argv[1]).reserve('crash','source');os._exit(7)"
            p=subprocess.run([sys.executable,'-c',code,str(b.path)],capture_output=True)
            self.assertEqual(p.returncode,7)
            self.assertEqual(DurableBudget(b.path).reserve('crash','source'),'already_reserved_do_not_execute')
            b.stop('platform_warning')
            self.assertEqual(DurableBudget(b.path).reserve('new','source'),'stop')
            self.assertEqual(len(b.snapshot()['operations']),1)

    def test_failures_retry_and_unknown_totals_do_not_reset(self):
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td,used=dict(USED,source=10))
            self.assertEqual(b.reserve('source','source'),'reserved')
            self.assertEqual(b.reserve('retry','retry',parent='source',failure='transient'),'reserved')
            self.assertEqual(b.reserve('more','source'),'skip_partial')
            self.assertEqual(b.reserve('retry2','retry',parent='source',failure='transient'),'skip_partial')
            with self.assertRaises((ValueError,FileExistsError)):self.make(td)
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td,used=dict(USED,source=None))
            with self.assertRaisesRegex(ValueError,'unknown'):b.reserve('new','source')
            self.assertEqual(b.snapshot()['seed']['used']['source'],None)
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td);b.reserve('s','source')
            for reason in ('validation','unknown_outcome','platform_limit'):
                self.assertEqual(b.reserve(reason,'retry',parent='s',failure=reason),'skip_partial')

    def test_candidate_history_preserved_and_atomic_registration(self):
        recent=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        history=[{'attempted_at':recent,'counts_toward_next_7_day_change_budget':True},
                 {'attempted_at':recent,'counts_toward_next_7_day_change_budget':True}]
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td,history=history)
            self.assertEqual(b.reserve('c','candidate'),'skip_partial')
            self.assertEqual(b.snapshot()['seed']['candidate_history'],history)
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td)
            self.assertEqual(b.reserve('later','candidate'),'reserved')
            self.assertEqual(DurableBudget(b.path).reserve('second','candidate'),'skip_partial')
            self.assertEqual(b.reserve('eval','evaluation',parent='later'),'reserved')
            self.assertEqual(b.reserve('eval-again','evaluation',parent='later'),'skip_partial')
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td,history=None)
            with self.assertRaisesRegex(ValueError,'history'):b.reserve('c','candidate')

    def test_missing_corrupt_unprivate_symlink_hardlink_and_readonly_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'missing'
            with self.assertRaises((OSError,ValueError)):DurableBudget(p).snapshot()
            self.assertFalse(p.exists())
            b=self.make(td);alias=Path(td)/'link';alias.symlink_to(b.path)
            with self.assertRaises((OSError,ValueError)):DurableBudget(alias).snapshot()
            os.link(b.path,Path(td)/'hard')
            with self.assertRaises((OSError,ValueError)):b.snapshot()
            (Path(td)/'hard').unlink();b.path.chmod(0o400)
            with self.assertRaises((OSError,ValueError)):b.reserve('s','source')
            b.path.chmod(0o600);b.path.write_bytes(b'corrupt')
            with self.assertRaises((sqlite3.Error,ValueError)):b.snapshot()
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td);Path(td).chmod(0o755)
            with self.assertRaises((OSError,ValueError)):b.reserve('s','source')
            Path(td).chmod(0o700)

    def test_identity_collision_payload_and_ledger_integrity_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td);b.reserve('same','source',payload={'a':1})
            with self.assertRaisesRegex(ValueError,'different'):b.reserve('same','llm',payload={'a':1})
            with self.assertRaisesRegex(ValueError,'different'):b.reserve('same','source',payload={'a':2})
            with sqlite3.connect(b.path) as c:c.execute("UPDATE state SET body='{}'")
            with self.assertRaises(ValueError):b.reserve('s','source')

    def test_uncommitted_crash_rolls_back_and_llm_limit_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td,used=dict(USED,llm=11))
            code="import sqlite3,sys,os;c=sqlite3.connect(sys.argv[1]);c.execute('BEGIN IMMEDIATE');c.execute(\"UPDATE state SET body='corrupt-uncommitted'\");os._exit(9)"
            p=subprocess.run([sys.executable,'-c',code,str(b.path)],capture_output=True)
            self.assertEqual(p.returncode,9)
            self.assertEqual(b.reserve('model-last','llm'),'reserved')
            self.assertEqual(DurableBudget(b.path).reserve('model-over','llm'),'skip_partial')
            self.assertEqual(b.reserve('model-last','llm'),'already_reserved_do_not_execute')

    def test_unsafe_sidecar_and_checkout_ledger_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            b=self.make(td);target=Path(td)/'target';target.write_bytes(b'');target.chmod(0o600)
            journal=Path(str(b.path)+'-journal');journal.symlink_to(target)
            with self.assertRaises((OSError,ValueError)):b.snapshot()
            journal.unlink()
            (Path(td)/'.git').mkdir()
            with self.assertRaisesRegex(ValueError,'checkout'):b.snapshot()

    def test_bad_seed_never_creates_file_or_expands_caps(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'budget.sqlite'
            for used in ({},dict(USED,llm=True),dict(USED,source=-1)):
                with self.assertRaises(ValueError):DurableBudget.create(p,run_id='synthetic',used=used,candidate_history=[])
                self.assertFalse(p.exists())

    def test_sqlite_uri_special_filename_cannot_open_another_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'budget ?#.sqlite'
            b=DurableBudget.create(p,run_id='synthetic',used=USED,candidate_history=[])
            self.assertEqual(b.reserve('one','source'),'reserved')
            self.assertEqual(len(DurableBudget(p).snapshot()['operations']),1)
            self.assertFalse((Path(td)/'budget ').exists())
