from datetime import datetime, timedelta, timezone
import json

import pytest

from noesis.ask import ask, search_terms
from noesis.config import initialize
from noesis.db import Database
from noesis.digest import client
from noesis.models import Event

SECRET = 'sk-' + 'X' * 24


def setup(tmp_path, content='我们讨论了数据库索引，最后决定先做 trigram 搜索。'):
    config = initialize(tmp_path / 'data')
    now = datetime.now(timezone.utc)
    with Database(config.db_path) as db:
        db.upsert_events([
            Event('codex', 'one', 'user_msg', now, content=content, session_id='s1', project='noesis',
                  title='数据库索引讨论'),
            Event('capture', '20261030-120000-abcd', 'capture', now - timedelta(days=10),
                  title='收藏笔记', content='截图记录：另一种索引方案。',
                  meta={'screenshot': 'captures/2026-10/20261030-120000-abcd.png'}),
        ])
    return config


def fake_completion(seen=None):
    def complete(settings, system, payload, *, env_file=None):
        if seen is not None:
            seen.append(payload)
        return ({'answer': '你决定先实现 trigram 搜索 [E1]。', 'citations': ['E1']},
                {'prompt_tokens': 30, 'completion_tokens': 12, 'total_tokens': 42}, 'deepseek-flash')
    return complete


def test_ask_returns_cited_answer_and_redacts_evidence(tmp_path, monkeypatch):
    config = setup(tmp_path, content='我们决定做数据库索引。token=' + SECRET)
    seen = []
    monkeypatch.setattr('noesis.ask.client.complete', fake_completion(seen))
    result = ask(config, '数据库索引做了什么？')
    assert result['mode'] == 'model' and result['citations'] == ['E1']
    assert result['answer'].endswith('[E1]。')
    assert result['evidence'][0]['id'] == 'E1'
    assert SECRET not in json.dumps(seen[0], ensure_ascii=False)
    assert result['usage']['total_tokens'] == 42


def test_ask_without_evidence_does_not_call_model(tmp_path, monkeypatch):
    config = setup(tmp_path)
    def fail(*args, **kwargs):
        raise AssertionError('model must not be called without evidence')
    monkeypatch.setattr('noesis.ask.client.complete', fail)
    result = ask(config, '完全不存在的主题')
    assert result['mode'] == 'no_data' and result['evidence'] == [] and result['citations'] == []


def test_ask_rejects_invalid_citation(tmp_path, monkeypatch):
    config = setup(tmp_path)
    monkeypatch.setattr('noesis.ask.client.complete', lambda *args, **kwargs: (
        {'answer': '答案 [E9]。', 'citations': ['E9']}, {}, 'deepseek-flash'))
    with pytest.raises(client.DigestError) as error:
        ask(config, '数据库索引做了什么？')
    assert str(error.value) == 'invalid_ask_citation'


def test_ask_allows_insufficient_answer_without_citations(tmp_path, monkeypatch):
    config = setup(tmp_path)
    monkeypatch.setattr('noesis.ask.client.complete', lambda *args, **kwargs: (
        {'answer': '记录不足以判断当时是否完成。', 'citations': []}, {}, 'deepseek-flash'))
    result = ask(config, '数据库索引做了什么？')
    assert result['citations'] == []


def test_ask_days_filter_and_cli_json(tmp_path, monkeypatch, capsys):
    from noesis.cli import main
    config = setup(tmp_path)
    monkeypatch.setattr('noesis.ask.client.complete', fake_completion())
    old = ask(config, '另一种索引方案', days=1)
    assert old['mode'] == 'no_data'
    assert main(['ask', '数据库索引做了什么？', '--json', '--data-dir', str(config.root)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['answer'].startswith('你决定') and output['evidence'][0]['id'] == 'E1'
    assert search_terms('我上周在数据库索引上做了什么？')[:2] == ['数据库', '据库索']


def test_cli_human_output_lists_cited_evidence(tmp_path, monkeypatch, capsys):
    from noesis.cli import main
    config = setup(tmp_path)
    monkeypatch.setattr('noesis.ask.client.complete', fake_completion())
    assert main(['ask', '数据库索引做了什么？', '--data-dir', str(config.root)]) == 0
    output = capsys.readouterr().out
    assert output.startswith('你决定先实现')
    assert '依据：' in output and '[E1]' in output and 'Codex' in output
