from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
import json
from pathlib import Path
from types import SimpleNamespace

from noesis import queries
from noesis.config import initialize
from noesis.db import Database
from noesis.models import Event
from noesis.render.daily import render_day,build_daily
from noesis.audit import audit_redaction
from noesis.install import install,uninstall,LABELS


def fixture_events():
    return [Event('codex','user','user_msg','2026-10-22T01:00:00Z',content='请实现\n```日志',session_id='s',project='demo'),
            Event('codex','assistant','assistant_msg','2026-10-22T01:05:00Z',content='已经完成。',session_id='s',project='demo',meta={'tools':[{'name':'Edit'}]}),
            Event('git','abcdef012345','commit','2026-10-22T01:06:00Z',title='feat: daily',project='demo',meta={'insertions':5,'deletions':2,'files_changed':1}),
            Event('capture','20261022-091000-abcd','capture','2026-10-22T01:10:00Z',title='参考资料',content='摘录',
                  meta={'screenshot':'captures/2026-10/20261022-091000-abcd.png','note':'保留这个想法'}),
            Event('browser_history','visit','visit','2026-10-22T02:00:00Z',title='示例网页',url='https://example.invalid/a',
                  meta={'domain':'example.invalid','duration_seconds':12})]


def test_daily_snapshot_and_determinism():
    with Database(':memory:') as db:
        db.upsert_events(fixture_events());db.refresh_sessions()
        text=render_day(db.connection,date(2026,10,22),'Asia/Shanghai')
        assert text==(Path(__file__).parent/'snapshots/daily.md').read_text()
        assert text==render_day(db.connection,date(2026,10,22),'Asia/Shanghai')
        assert '```日志' not in text and ' ⏎ ' in text


def test_catch_up_preserves_unchanged_files_and_detects_old_edits_and_deletes(tmp_path):
    config=initialize(tmp_path/'data');today=datetime.now(config.timezone).date()
    event=Event('codex','one','user_msg',datetime.now(timezone.utc)-timedelta(days=1),content='before',session_id='s')
    with Database(config.db_path) as db:db.insert_event(event);db.refresh_sessions()
    assert len(build_daily(config,catch_up=3)['written'])==3
    before={p.name:p.stat().st_mtime_ns for p in (config.root/'daily').glob('*.md')}
    assert not build_daily(config,catch_up=3)['written']
    assert before=={p.name:p.stat().st_mtime_ns for p in (config.root/'daily').glob('*.md')}
    with Database(config.db_path) as db:db.replace_event(replace(event,content='after'))
    assert build_daily(config,catch_up=3)['written']==[(today-timedelta(days=1)).isoformat()]
    with Database(config.db_path) as db:db.delete_events([event.id])
    assert build_daily(config,catch_up=3)['written']==[(today-timedelta(days=1)).isoformat()]


def test_audit_reports_only_locations_and_repairs_database_and_md(tmp_path):
    config=initialize(tmp_path/'data');secret='sk-'+'X'*24
    event=fixture_events()[0]
    with Database(config.db_path) as db:
        db.insert_event(event);db.refresh_sessions()
        db.connection.execute('UPDATE events SET content=? WHERE id=?',(secret,event.id))
    (config.root/'daily/2026-10-22.md').write_text('secret '+secret)
    report=audit_redaction(config)
    assert report['hits']==2 and secret not in json.dumps(report)
    fixed=audit_redaction(config,fix=True)
    assert fixed['remaining']==0 and fixed['fixed']==2
    assert secret not in (config.root/'daily/2026-10-22.md').read_text()
    assert audit_redaction(config)['hits']==0


def test_installer_is_idempotent_and_uninstall_preserves_data(tmp_path,monkeypatch):
    home=tmp_path/'home';home.mkdir()
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    config=initialize(tmp_path/'data');project=Path(__file__).resolve().parents[1]
    hs=home/'.hammerspoon';hs.mkdir();(hs/'init.lua').write_text('-- user setting\ncustom = true\n')
    monkeypatch.setattr('noesis.install.subprocess.run',lambda *args,**kw:SimpleNamespace(returncode=0,stdout=''))
    install(config,project,load=False)
    init=(hs/'init.lua').read_text();assert init.count('require("noesis")')==1 and 'custom = true' in init
    plists={label:(home/'Library/LaunchAgents'/f'{label}.plist').read_bytes() for label in LABELS}
    install(config,project,load=False)
    assert (hs/'init.lua').read_text()==init
    assert plists=={label:(home/'Library/LaunchAgents'/f'{label}.plist').read_bytes() for label in LABELS}
    import plistlib
    daily=plistlib.loads(plists[LABELS[1]])
    assert daily['StartCalendarInterval']=={'Hour':23,'Minute':30}
    assert 'daily-run' in daily['ProgramArguments'] and Path(daily['ProgramArguments'][0]).is_absolute()
    uninstall(config,load=False)
    assert config.db_path.exists() and 'custom = true' in (hs/'init.lua').read_text()
    assert not (hs/'noesis.lua').exists()
    uninstall(config,load=False)


def test_end_to_end_all_text_sources_redact_before_daily(tmp_path,monkeypatch):
    import sqlite3
    from noesis.collectors.collect import collect
    from noesis.capture.capture import create_capture,enrich_capture
    from noesis.capture import browser_bridge
    config=initialize(tmp_path/'data')
    config.values['sources']['git']=False
    secrets=['sk-'+chr(65+i)*24 for i in range(8)]
    now=datetime.now(timezone.utc);day=now.astimezone(config.timezone).date()
    cc=tmp_path/'cc';cc.mkdir();cx=tmp_path/'cx';cx.mkdir()
    config.values['claude_code']['root']=str(cc)
    config.values['codex']['sessions_root']=str(cx)
    config.values['codex']['history_file']=str(tmp_path/'missing-history')
    (cc/'session.jsonl').write_text(json.dumps({'type':'user','uuid':'one','sessionId':'cc','timestamp':now.isoformat(),
        'message':{'role':'user','content':' '.join(secrets[:2])}})+'\n')
    (cx/'rollout.jsonl').write_text(json.dumps({'type':'response_item','timestamp':now.isoformat(),'payload':{'type':'message','role':'user','id':'one',
        'content':[{'type':'input_text','text':' '.join(secrets[2:4])}]}})+'\n')
    history=tmp_path/'History'
    with sqlite3.connect(history) as connection:
        connection.executescript('CREATE TABLE urls(id INTEGER,url TEXT,title TEXT); CREATE TABLE visits(id INTEGER,url INTEGER,visit_time INTEGER,transition INTEGER,visit_duration INTEGER,from_visit INTEGER);')
        connection.execute('INSERT INTO urls VALUES (1,?,?)',('https://example.invalid/?key='+secrets[4]+'&access_token='+secrets[5],'example'))
        connection.execute('INSERT INTO visits VALUES (1,1,?,0,0,0)',(int((now-datetime(1601,1,1,tzinfo=timezone.utc)).total_seconds()*1e6),))
    config.values['browser']['enabled']=['chrome']
    config.values['browser']['profiles_glob']=[{'name':'chrome','glob':str(history),'kind':'chromium'}]
    collect(config)
    monkeypatch.setattr('noesis.capture.capture.screenshot',lambda path,**kwargs:path.write_bytes(b'synthetic image'))
    monkeypatch.setattr(browser_bridge,'metadata',lambda app:{})
    monkeypatch.setattr(browser_bridge,'page',lambda *args,**kwargs:{'text':' '.join(secrets[6:])})
    monkeypatch.setattr('noesis.capture.capture.subprocess.run',lambda *args,**kwargs:SimpleNamespace(returncode=0,stdout='{"text":"synthetic OCR","ms":1}'))
    capture=create_capture(config,background=False)
    enrich_capture(config,capture['id'])
    build_daily(config,day=day.isoformat())
    assert audit_redaction(config)['hits']==0
    for path in config.root.rglob('*.md'):
        text=path.read_text()
        assert all(secret not in text for secret in secrets)
    with Database(config.db_path) as db:
        dump='\n'.join(db.connection.iterdump())
        assert all(secret not in dump for secret in secrets)


def test_nightly_builds_even_when_a_source_is_partial(tmp_path,monkeypatch,capsys):
    from noesis.cli import main
    config=initialize(tmp_path/'data')
    monkeypatch.setattr('noesis.collectors.collect.collect',lambda *args,**kwargs:{'browser_history':{'status':'partial'}})
    assert main(['daily-run','--data-dir',str(config.root),'--catch-up','1'])==1
    report=json.loads(capsys.readouterr().out)
    assert len(report['daily']['written'])==1
