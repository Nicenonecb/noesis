from datetime import datetime, timedelta, timezone
import json

from noesis import queries
from noesis.config import initialize
from noesis.db import Database
from noesis.collectors.collect import collect
from noesis.collectors import codex
from noesis.collectors.common import read_file


def setup(tmp_path):
    config=initialize(tmp_path/'data')
    root=tmp_path/'sessions';root.mkdir()
    config.values['codex']['sessions_root']=str(root)
    config.values['codex']['history_file']=str(tmp_path/'history.jsonl')
    config.values['sources']['claude_code']=False
    config.values['sources']['git']=False
    config.values['sources']['browser_history']=False
    return config,root/'rollout.jsonl'


def write(path,rows):
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows))


def message(role,text,stamp='2026-10-22T00:00:00Z'):
    return {'type':'response_item','timestamp':stamp,'payload':{'type':'message','role':role,'id':role+text,
                                                            'content':[{'type':'output_text','text':text}]}}


def test_preferred_channels_tools_and_empty_session(tmp_path):
    config,path=setup(tmp_path)
    write(path,[{'type':'session_meta','payload':{'id':'s','cwd':'/demo','timestamp':'2026-10-22T00:00:00Z','cli_version':'test'}},
                message('user','hello'), {'type':'event_msg','timestamp':'2026-10-22T00:00:01Z','payload':{'type':'user_message','message':'hello'}},
                message('assistant','answer'),
                {'type':'response_item','timestamp':'2026-10-22T00:00:02Z','payload':{'type':'function_call','name':'exec','call_id':'tool','arguments':'{"cmd":"echo hello","password":"hidden"}'}}])
    collect(config,'codex')
    with Database(config.db_path) as db:
        events=queries.get_session_events(db.connection,'s')
        assert len(events)==2
        user=next(e for e in events if e.kind=='user_msg')
        assistant=next(e for e in events if e.kind=='assistant_msg')
        assert user.meta['channel']=='legacy' and user.ts.endswith('01.000000Z')
        assert assistant.meta['tools']==[{'name':'exec','summary':'echo hello'}]
        assert 'hidden' not in '\n'.join(db.connection.iterdump())
    collect(config,'codex',backfill='all')
    with Database(config.db_path) as db:
        assert len(next(e for e in queries.get_session_events(db.connection,'s') if e.kind=='assistant_msg').meta['tools'])==1
    empty=path.with_name('empty.jsonl')
    write(empty,[{'type':'session_meta','payload':{'id':'empty','timestamp':'2026-10-22T00:00:00Z'}}])
    collect(config,'codex')
    with Database(config.db_path) as db:
        assert queries.session_record(db.connection,'codex','empty').n_user==0


def test_history_five_seconds_and_occurrence_survive_repeated_runs(tmp_path):
    config,path=setup(tmp_path)
    stamp='2026-10-22T00:00:00Z'
    write(path,[{'type':'session_meta','payload':{'id':'s'}},message('user','same',stamp)])
    seconds=int(datetime.fromisoformat(stamp).timestamp())
    history=config.source_path('codex','history_file')
    write(history,[{'session_id':'s','ts':seconds+5,'text':'same'}]*2+
                  [{'session_id':'s','ts':seconds+6,'text':'different'}])
    for backfill in ('all',None,'all',None):
        collect(config,'codex',backfill=backfill)
        with Database(config.db_path) as db:
            events=queries.get_session_events(db.connection,'s')
            assert len(events)==3
            assert sum(e.meta.get('from_history',False) for e in events)==2


def test_backfill_filters_dates_and_dry_run_changes_nothing(tmp_path):
    config,path=setup(tmp_path)
    now=datetime.now(timezone.utc)
    write(path,[{'type':'session_meta','payload':{'id':'s'}},
                message('user','old',(now-timedelta(days=30)).isoformat()),message('user','new',now.isoformat())])
    before={str(file):file.read_bytes() for file in config.root.rglob('*') if file.is_file() and not file.name.endswith(('-wal','-shm'))}
    result=collect(config,'codex',backfill=timedelta(days=7),dry_run=True)
    assert result['codex']['inserted']==1
    after={str(file):file.read_bytes() for file in config.root.rglob('*') if file.is_file() and not file.name.endswith(('-wal','-shm'))}
    assert before==after
    collect(config,'codex',backfill=timedelta(days=7))
    with Database(config.db_path) as db:
        assert [e.content for e in queries.get_session_events(db.connection,'s')]==['new']
        assert db.get_cursor('codex',str(path.resolve()))['offset']==path.stat().st_size
    collect(config,'codex',backfill='all')
    with Database(config.db_path) as db:
        assert len(queries.get_session_events(db.connection,'s'))==2
