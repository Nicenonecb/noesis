import json
from pathlib import Path

from noesis.collectors import claude_code
from noesis.collectors.common import read_file
from noesis.config import initialize
from noesis.db import Database
from noesis import queries


def row(uuid, text, **extra):
    return dict(type='assistant', uuid=uuid, sessionId='s', cwd='/demo', timestamp='2026-10-22T00:00:00Z',
                message={'role':'assistant','id':'message','content':[{'type':'text','text':text}]}, **extra)


def append(path, records):
    with path.open('a') as file:
        for record in records:
            file.write(json.dumps(record) + '\n')


def test_fragments_merge_across_runs_and_replay(tmp_path):
    config = initialize(tmp_path / 'data')
    path = tmp_path / 'session.jsonl'
    append(path, [row('one','第一段')])
    with Database(config.db_path) as db:
        parse = claude_code.parser(config.values['claude_code'])
        read_file(db, path, 'claude_code', parse)
        append(path, [row('two','第二段'),row('three','第三段')])
        read_file(db, path, 'claude_code', parse)
        events = queries.get_session_events(db.connection, 's')
        assert len(events) == 1 and events[0].content == '第一段\n第二段\n第三段'
        before = events[0]
        read_file(db, path, 'claude_code', parse, replay=True)
        assert queries.get_session_events(db.connection,'s')[0] == before


def test_commands_summary_tools_and_truncation(tmp_path):
    config = initialize(tmp_path/'data')
    settings = config.values['claude_code'] | {'max_assistant_chars': 4}
    path=tmp_path/'session.jsonl'
    command = row('command', '')
    command['type']='user'
    command['message']={'role':'user','content':'<command-name>/review</command-name><command-args>file.py</command-args>'}
    tool=row('tool','')
    tool['message']['content']=[{'type':'tool_use','name':'Edit','input':{'file_path':'a.py','password':'never'}}]
    append(path,[command,row('one','abcdef'),tool,row('two','ghijkl'),
                 {'type':'summary','sessionId':'s','summary':'总结标题'}])
    with Database(config.db_path) as db:
        read_file(db,path,'claude_code',claude_code.parser(settings))
        db.refresh_sessions()
        events=queries.get_session_events(db.connection,'s')
        assistant=next(e for e in events if e.kind=='assistant_msg')
        assert assistant.content=='abcd…[truncated 9 chars]'
        assert assistant.meta['tools']==[{'name':'Edit','summary':'a.py'}]
        user=next(e for e in events if e.kind=='user_msg')
        assert user.content=='/review file.py' and user.meta['is_command']
        assert queries.session_record(db.connection,'claude_code','s').title=='总结标题'
        assert 'never' not in '\n'.join(db.connection.iterdump())


def test_old_fragment_rows_are_replaced_on_replay(tmp_path):
    from noesis.models import Event
    config=initialize(tmp_path/'data')
    path=tmp_path/'session.jsonl'
    append(path,[row('one','first'),row('two','second')])
    with Database(config.db_path) as db:
        for i, uid in enumerate(['one','two'],1):
            db.insert_event(Event('claude_code',f's:{uid}','assistant_msg','2026-10-22T00:00:00Z',
                                  content=uid,session_id='s',raw_ref=f'{path}:{i}'))
        db.connection.commit()
        read_file(db,path,'claude_code',claude_code.parser(config.values['claude_code']),replay=True)
        events=queries.get_session_events(db.connection,'s')
        assert len(events)==1 and events[0].content=='first\nsecond'


def test_whole_file_sidechain_and_configurable_strip(tmp_path):
    path=tmp_path/'sidechain.jsonl'
    append(path,[row('one','first'),row('two','second',isSidechain=True)])
    assert claude_code.is_sidechain(path)
    config=initialize(tmp_path/'data')
    settings=config.values['claude_code'] | {'strip_tags':['custom-injection']}
    record=row('user','')
    record['type']='user'
    record['message']={'role':'user','content':'<custom-injection>private</custom-injection>正文'}
    event=claude_code.parser(settings)(record,{},path,1)
    assert event.content=='正文'
