import os,sqlite3,json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root=Path.cwd();assert root.name=='fixture' and root.parent.name=='preflight'
assert os.environ['LEGALDEBATE_DB_URL']=='sqlite:///database/codex_runs.db'
assert os.environ['POWERSHELL_TELEMETRY_OPTOUT']=='1'
db=root/'database/codex_runs.db';con=sqlite3.connect(db)
assert not con.execute("select name from sqlite_master where name='__codex_env_probe'").fetchall()
con.execute('BEGIN IMMEDIATE')
con.execute('CREATE TABLE __codex_env_probe (v INTEGER NOT NULL)')
con.execute('INSERT INTO __codex_env_probe VALUES (1)')
sidecar_during_transaction=any(Path(str(db)+s).exists() for s in ['-journal','-wal'])
assert sidecar_during_transaction
con.commit();con.close()
con=sqlite3.connect(db);assert con.execute('SELECT v FROM __codex_env_probe').fetchall()==[(1,)]
for v in [2,3]:con.execute('INSERT INTO __codex_env_probe VALUES (?)',(v,));con.commit()
con.execute('INSERT INTO __codex_env_probe VALUES (999)');con.rollback()
assert con.execute('SELECT v FROM __codex_env_probe ORDER BY v').fetchall()==[(1,),(2,),(3,)]
con.execute('DROP TABLE __codex_env_probe');con.commit();con.close()
negative={}
for name in ['db.py','schema.py']:
 p=root/'database'/name
 try:
  p.open('r+b').close();negative[name+'_write_denied']=False
 except PermissionError:negative[name+'_write_denied']=True
 try:
  p.unlink();negative[name+'_delete_denied']=False
 except PermissionError:negative[name+'_delete_denied']=True
p=root/'database/legal_debate.db'
try:p.open('rb').close();negative['formal_sentinel_read_denied']=False
except PermissionError:negative['formal_sentinel_read_denied']=True
assert all(negative.values()),negative
print(json.dumps({'sqlite_commit_reopen_rollback':True,'repeated_commit':True,'sidecar_observed':sidecar_during_transaction,'negative_checks':negative,'no_main_or_verify_invoked':True,'network_requests_in_program':0},ensure_ascii=False))
