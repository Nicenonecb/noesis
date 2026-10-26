from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from noesis.config import initialize
from noesis.collectors.collect import collect
from noesis.collectors.browser_history import visit_event
from noesis.db import Database
from noesis import queries


BASE=13437104400000000  # 2026-10-22 01:00 UTC, Chromium epoch.


def setup(tmp_path):
    path=tmp_path/'Default'/'History';path.parent.mkdir()
    source=sqlite3.connect(path)
    source.execute('PRAGMA journal_mode=WAL')
    source.execute('PRAGMA wal_autocheckpoint=0')
    source.executescript('''CREATE TABLE urls(id INTEGER PRIMARY KEY,url TEXT,title TEXT);
        CREATE TABLE visits(id INTEGER PRIMARY KEY,url INTEGER,visit_time INTEGER,transition INTEGER,visit_duration INTEGER,from_visit INTEGER);''')
    config=initialize(tmp_path/'data')
    config.values['browser']|={'enabled':['chrome'],'profiles_glob':[{'name':'chrome','glob':str(path),'kind':'chromium'}],
                               'blacklist_domains':['private.invalid'],'blacklist_url_regex':['/blocked']}
    return config,path,source


def add(source,identity,url,at=BASE,transition=0):
    source.execute('INSERT INTO urls VALUES (?,?,?)',(identity,url,'测试标题'))
    source.execute('INSERT INTO visits VALUES (?,?,?,?,?,?)',(identity,identity,at,transition,1_000_000,0))
    source.commit()


def events(config):
    with Database(config.db_path) as db:
        start=datetime(2026,1,1,tzinfo=timezone.utc);end=datetime(2027,1,1,tzinfo=timezone.utc)
        return queries.get_events(db.connection,start=start,end=end,sources=['browser_history'])


def test_live_wal_filter_redaction_merge_and_repeat(tmp_path):
    config,path,source=setup(tmp_path)
    try:
        add(source,1,'https://www.example.invalid/page?token=secret&utm_source=x&x=1')
        add(source,2,'https://www.example.invalid/page?token=secret&utm_source=y&x=1',BASE+30_000_000)
        add(source,3,'https://private.invalid/page',BASE+31_000_000)
        add(source,4,'https://example.invalid/subframe',BASE+32_000_000,3)
        add(source,5,'http://127.0.0.1/test',BASE+33_000_000)
        add(source,6,'https://example.invalid/blocked',BASE+34_000_000)
        before=(path.read_bytes(),Path(str(path)+'-wal').read_bytes())
        result=collect(config,'browser_history')['browser_history']
        assert result['inserted']==1 and result['merged']==1
        assert before==(path.read_bytes(),Path(str(path)+'-wal').read_bytes())
        event=events(config)[0]
        assert event.ts=='2026-10-22T01:00:00.000000Z'
        assert event.meta['repeat']==1 and event.meta['duration_seconds']==2
        assert event.meta['domain']=='example.invalid'
        assert 'secret' not in json.dumps(event.meta) and 'utm_source' not in event.url
        assert 'utm_source' in event.meta['url_raw']
        collect(config,'browser_history')
        assert events(config)[0].meta['repeat']==1
        collect(config,'browser_history',backfill='all')
        assert len(events(config))==1 and events(config)[0].meta['repeat']==1
    finally:source.close()


def test_cross_run_merge_and_equal_timestamp_new_visit(tmp_path):
    config,path,source=setup(tmp_path)
    try:
        add(source,1,'https://example.invalid/a')
        collect(config,'browser_history')
        add(source,2,'https://example.invalid/a',BASE+10_000_000)
        collect(config,'browser_history')
        assert len(events(config))==1 and events(config)[0].meta['repeat']==1
        add(source,3,'https://example.invalid/b',BASE+10_000_000)
        collect(config,'browser_history')
        assert len(events(config))==2
    finally:source.close()


def test_safari_epoch_and_permission_failure_isolated(tmp_path,monkeypatch):
    config,path,source=setup(tmp_path)
    safari=tmp_path/'Safari'/'History.db';safari.parent.mkdir();safari.write_bytes(b'placeholder')
    config.values['browser']['enabled'].append('safari')
    config.values['browser']['profiles_glob'].append({'name':'safari','glob':str(safari),'kind':'safari'})
    add(source,1,'https://example.invalid/a')
    from noesis.collectors import browser_history
    original=browser_history.history_snapshot
    def denied(path):
        if path==safari:raise PermissionError()
        return original(path)
    monkeypatch.setattr(browser_history,'history_snapshot',denied)
    try:
        result=collect(config,'browser_history')['browser_history']
        assert result['status']=='partial' and result['inserted']==1 and result['failed_files']==1
    finally:source.close()
    timestamp=(datetime(2026,10,22,1,tzinfo=timezone.utc)-datetime(2001,1,1,tzinfo=timezone.utc)).total_seconds()
    event=visit_event({'id':1,'url':'https://example.invalid/','title':'','visit_time':timestamp},
                      {'name':'safari','kind':'safari'},safari,config.values['browser'])
    assert event.ts=='2026-10-22T01:00:00.000000Z'
