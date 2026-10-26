import os
from pathlib import Path
import subprocess

from noesis.config import initialize
from noesis.db import Database
from noesis.collectors.collect import collect
from noesis import queries
from noesis.models import Event


def git(path,*args,**kwargs):
    return subprocess.run(['git','-C',str(path),*args],check=True,capture_output=True,text=True,**kwargs).stdout.strip()


def repo(path):
    path.mkdir()
    git(path,'init','-b','main')
    for key,value in [('user.name','Synthetic'),('user.email','own@example.invalid'),('commit.gpgsign','false'),('core.hooksPath','/dev/null')]:
        git(path,'config',key,value)
    return path


def commit(path,name,content,email='own@example.invalid'):
    (path/name).write_bytes(content)
    git(path,'add',name)
    env=os.environ | {'GIT_AUTHOR_EMAIL':email,'GIT_COMMITTER_EMAIL':email}
    git(path,'commit','-m',name,env=env)
    return git(path,'rev-parse','HEAD')


def test_discovery_author_worktree_numstat_and_reproject(tmp_path):
    root=repo(tmp_path/'project')
    first=commit(root,'a.txt',b'one\ntwo\n')
    other=commit(root,'other.txt',b'other\n','other@example.invalid')
    binary=commit(root,'image.bin',b'\x00\x01binary')
    worktree=tmp_path/'linked'
    git(root,'worktree','add','-b','feature',str(worktree))
    (root/'scripts').mkdir()
    config=initialize(tmp_path/'data')
    config.values['git']|={'repos':[str(worktree),str(root)],'scan_roots':[str(tmp_path)],'author_emails':['own@example.invalid']}
    with Database(config.db_path) as db:
        for index,cwd in enumerate([root/'scripts',worktree]):
            db.insert_event(Event('codex',str(index),'user_msg','2026-10-22T00:00:00Z',content='hello',session_id=str(index),
                                  project=cwd.name,meta={'cwd':str(cwd)}))
        db.refresh_sessions()
    result=collect(config,'git',backfill='all')['git']
    assert result['status']=='ok' and result['inserted']==2
    with Database(config.db_path) as db:
        repos=queries.get_repos(db.connection)
        assert len(repos)==1 and repos[0]['name']=='project'
        rows=db.connection.execute("SELECT source_id,meta FROM events WHERE source='git'").fetchall()
        assert {row['source_id'] for row in rows}=={first,binary}
        assert all(e.project=='project' for id in ('0','1') for e in queries.get_session_events(db.connection,id,source='codex'))
        import json
        meta={row['source_id']:json.loads(row['meta']) for row in rows}
        assert meta[first]['insertions']==2 and meta[binary]['insertions']==0
        assert meta[binary]['files_changed']==1
    assert collect(config,'git')['git']['inserted']==0
    with Database(config.db_path) as db:
        db.set_repo_enabled(root,False)
    assert collect(config,'git')['git'].get('files',0)==0


def test_rename_and_merge(tmp_path):
    root=repo(tmp_path/'project')
    commit(root,'before.txt',b'a\nb\nc\n')
    git(root,'checkout','-b','side')
    commit(root,'side.txt',b'side\n')
    git(root,'checkout','main')
    git(root,'mv','before.txt','after.txt')
    git(root,'commit','-m','rename')
    git(root,'merge','--no-ff','side','-m','merge')
    config=initialize(tmp_path/'data')
    config.values['git']|={'repos':[str(root)],'scan_roots':[],'discover_from_sessions':False}
    result=collect(config,'git',backfill='all')['git']
    assert result['status']=='ok' and result['inserted']==4
    import json
    with Database(config.db_path) as db:
        metadata=[json.loads(row[0]) for row in db.connection.execute("SELECT meta FROM events WHERE source='git'")]
        assert sum(m['is_merge'] for m in metadata)==1
        assert any('after.txt' in m['files'] for m in metadata)


def test_rewritten_commit_is_seen_with_overlap(tmp_path):
    root=repo(tmp_path/'project')
    original=commit(root,'a.txt',b'first\n')
    config=initialize(tmp_path/'data')
    config.values['git']|={'repos':[str(root)],'scan_roots':[],'discover_from_sessions':False}
    collect(config,'git')
    git(root,'commit','--amend','-m','rewritten')
    rewritten=git(root,'rev-parse','HEAD')
    result=collect(config,'git')['git']
    assert result['inserted']==1
    with Database(config.db_path) as db:
        assert {row[0] for row in db.connection.execute("SELECT source_id FROM events WHERE source='git'")}=={original,rewritten}
