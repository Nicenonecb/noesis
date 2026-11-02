from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from noesis import queries
from noesis.collectors.collect import collect
from noesis.config import initialize
from noesis.db import Database
from noesis.render.daily import render_day

pytestmark = pytest.mark.skipif(shutil.which('zstd') is None, reason='zstd CLI required')


def milliseconds(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)


def write_session(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = ('\n'.join(json.dumps(record, ensure_ascii=False) for record in records) + '\n').encode()
    with path.open('wb') as output:
        subprocess.run(['zstd', '-q', '-c'], input=payload, stdout=output, check=True)


def records(title='数据库索引检查'):
    return [
        {'type': 'session', 'version': 4, 'id': 'session-one', 'createdAt': milliseconds('2026-11-01T01:00:00Z'),
         'cwd': '/Users/example/Desktop/demo', 'isSeeded': False, 'delegationDepth': 0, 'agentPreset': 'default'},
        {'type': 'user/message', 'seq': 1, 'time': milliseconds('2026-11-01T01:01:00Z'),
         'data': {'content': [{'type': 'text', 'text': '请检查数据库索引。'}], 'source': {'kind': 'runtime-context'},
                  'role': 'user', 'id': 'injected'}},
        {'type': 'user/message', 'seq': 2, 'time': milliseconds('2026-11-01T01:02:00Z'),
         'data': {'content': [{'type': 'text', 'text': '请检查数据库索引。'}], 'source': {'kind': 'user'},
                  'role': 'user', 'id': 'user-one'}},
        {'type': 'assistant/message', 'seq': 3, 'time': milliseconds('2026-11-01T01:03:00Z'),
         'data': {'turn': 1, 'step': 1, 'message': {'role': 'assistant', 'id': 'assistant-one',
                  'content': [{'type': 'reasoning', 'text': '内部推理不应入库'},
                              {'type': 'text', 'text': '已检查数据库索引，并运行了测试。'}]}}},
        {'type': 'session/title', 'seq': 4, 'time': milliseconds('2026-11-01T01:04:00Z'),
         'data': {'title': title}},
    ]


def setup(tmp_path):
    config = initialize(tmp_path / 'data')
    root = tmp_path / 'dsh'
    config.values['dsh']['root'] = str(root)
    path = root / '--Users-example-Desktop-demo--' / 'session-one' / 'session.v4.jsonl.zstd'
    write_session(path, records())
    return config, path


def test_dsh_collects_messages_title_and_project(tmp_path):
    config, _ = setup(tmp_path)
    result = collect(config, 'dsh')
    assert result['dsh']['inserted'] == 2 and result['dsh']['status'] == 'ok'
    with Database(config.db_path) as db:
        events = queries.get_events(db.connection, start=datetime(2026, 10, 31, tzinfo=timezone.utc),
                                    end=datetime(2026, 11, 2, tzinfo=timezone.utc), sources=['dsh'])
        assert [event.kind for event in events] == ['user_msg', 'assistant_msg']
        assert events[0].source_id.endswith(':user:user-one')
        assert events[0].project == 'demo' and events[0].session_id == 'session-one'
        assert '内部推理' not in events[1].content and '数据库索引' in events[1].content
        session = queries.session_record(db.connection, 'dsh', 'session-one')
        assert session.title == '数据库索引检查' and session.n_user == 1 and session.n_assistant == 1
        daily = render_day(db.connection, date(2026, 11, 1), 'Asia/Shanghai')
        assert 'DSH' in daily and '数据库索引检查' in daily and '数据库索引' in daily


def test_dsh_cursor_skips_unchanged_and_reads_appends(tmp_path):
    config, path = setup(tmp_path)
    assert collect(config, 'dsh')['dsh']['inserted'] == 2
    second = collect(config, 'dsh')['dsh']
    assert second['inserted'] == 0 and second['skipped_files'] == 1
    write_session(path, records() + [
        {'type': 'user/message', 'seq': 5, 'time': milliseconds('2026-11-01T01:05:00Z'),
         'data': {'content': [{'type': 'text', 'text': '再补一条。'}], 'source': {'kind': 'user'},
                  'role': 'user', 'id': 'user-two'}},
    ])
    third = collect(config, 'dsh')['dsh']
    assert third['inserted'] == 1 and third['duplicates'] == 2


def test_dsh_backfill_filters_events(tmp_path):
    config, _ = setup(tmp_path)
    recent = collect(config, 'dsh', backfill='all')['dsh']
    assert recent['inserted'] == 2
    old = collect(config, 'dsh', backfill=timedelta(days=1))['dsh']
    assert old['inserted'] == 0 and old['filtered_by_date'] == 2


def test_v004_migration_preserves_existing_events_and_sessions(tmp_path):
    from noesis.migrations import v001, v002, v003
    path = tmp_path / 'old.sqlite'
    connection = sqlite3.connect(path)
    for migration in (v001, v002, v003):
        migration.apply(connection)
    connection.execute('PRAGMA user_version=3')
    connection.execute("""INSERT INTO events(id,source,kind,ts,content,meta,raw_ref,importance,created_at,source_id)
        VALUES('old','codex','user_msg','2026-11-01T00:00:00.000000Z','hello','{}','ref','normal','2026-11-01T00:00:00.000000Z','s')""")
    connection.execute("""INSERT INTO sessions(id,source,session_id,title,started_at,ended_at,n_user,n_assistant,raw_path)
        VALUES('hash','codex','s','title','2026-11-01T00:00:00.000000Z','2026-11-01T00:00:00.000000Z',1,0,'ref')""")
    connection.commit()
    connection.close()
    with Database(path) as db:
        assert db.connection.execute('PRAGMA user_version').fetchone()[0] == 4
        assert db.connection.execute('SELECT count(*) FROM events').fetchone()[0] == 1
        assert db.connection.execute('SELECT count(*) FROM sessions').fetchone()[0] == 1
        assert db.connection.execute("SELECT count(*) FROM events_fts WHERE events_fts MATCH 'hello'").fetchone()[0] == 1


def test_dsh_dry_run_does_not_write_events(tmp_path):
    config, _ = setup(tmp_path)
    result = collect(config, 'dsh', dry_run=True)
    assert result['dsh']['inserted'] == 2 and result['dsh']['dry_run'] is True
    with Database(config.db_path) as db:
        assert db.connection.execute("SELECT count(*) FROM events WHERE source='dsh'").fetchone()[0] == 0
