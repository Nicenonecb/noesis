import json
from pathlib import Path
import shutil

import pytest

from noesis.config import Config, initialize
from noesis.db import Database
from noesis.collectors.collect import collect
from noesis.collectors.common import human_text, read_file
from noesis.collectors import claude_code, codex

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config(tmp_path):
    original = initialize(tmp_path / "data")
    values = original.values
    for name, key in [("claude_code", "root"), ("codex", "sessions_root")]:
        root = tmp_path / name
        root.mkdir()
        values[name][key] = str(root)
    values["codex"]["history_file"] = str(tmp_path / "history.jsonl")
    return Config(original.root, values)


def rows(config):
    with Database(config.db_path) as db:
        return [dict(row) for row in db.connection.execute("SELECT * FROM events ORDER BY rowid")]


def write(path, records):
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))


def user(identity="one", text="你好", **extra):
    return {"type": "user", "uuid": identity, "sessionId": "session", "timestamp": "2026-10-22T01:00:00Z",
            "message": {"role": "user", "content": text}, **extra}


def test_fixtures_filter_dedup_and_history(config):
    shutil.copy(FIXTURES / "claude_code.jsonl", config.source_path("claude_code", "root"))
    for fixture in ["codex_current.jsonl", "codex_legacy_candidate.jsonl"]:
        shutil.copy(FIXTURES / fixture, config.source_path("codex", "sessions_root"))
    shutil.copy(FIXTURES / "codex_history.jsonl", config.source_path("codex", "history_file"))
    report = collect(config)
    data = rows(config)
    assert len([row for row in data if row["source"] == "claude_code"]) == 4
    assert len([row for row in data if row["source"] == "codex"]) == 8
    assert sum(row["content"] == "给示例项目增加离线初始化命令。" for row in data) == 2
    joined = json.dumps(data, ensure_ascii=False)
    for forbidden in ["合成的推理", "不得存储", "缓存镜像", "合成基础说明", "丢弃工具结果", "假工具参数"]:
        assert forbidden not in joined
    assert report["codex"]["history_reconciled"] == 1
    assert report["codex"]["unknown_records"] == 1
    assert report["claude_code"]["unknown_records"] == 1
    second = collect(config)
    assert not any(result.get("inserted") for result in second.values())
    assert rows(config) == data
    collect(config, replay=True)
    assert rows(config) == data


def test_append_partial_utf8_and_malformed(config):
    path = config.source_path("claude_code", "root") / "session.jsonl"
    first = (json.dumps(user(), ensure_ascii=False) + "\n").encode()
    second = (json.dumps(user("two", "继续写入中文"), ensure_ascii=False) + "\n").encode()
    split = second.index("中".encode()) + 1
    path.write_bytes(first + b'{"invalid":\n' + second[:split])
    report = collect(config, "claude_code")["claude_code"]
    assert report["invalid_lines"] == 1
    assert report["pending_tails"] == 1
    assert len(rows(config)) == 1
    with path.open("ab") as handle:
        handle.write(second[split:])
    assert collect(config, "claude_code")["claude_code"]["inserted"] == 1
    assert len(rows(config)) == 2


@pytest.mark.parametrize("mode", ["truncate", "rewrite", "replace"])
def test_source_rewrites(config, mode):
    path = config.source_path("claude_code", "root") / "session.jsonl"
    write(path, [user("one"), user("two")])
    collect(config, "claude_code")
    if mode == "replace":
        replacement = path.with_suffix(".new")
        write(replacement, [user("new"), user("two")])
        replacement.replace(path)
    elif mode == "rewrite":
        original_size = path.stat().st_size
        write(path, [user("new"), user("two")])
        assert path.stat().st_size == original_size
    else:
        write(path, [user("new")])
    report = collect(config, "claude_code")["claude_code"]
    assert report["resets"] == 1
    assert report["inserted"] == 1
    assert len(rows(config)) == 3


def test_transaction_rollback_and_replay_preserve_cursor(config, monkeypatch):
    path = config.source_path("claude_code", "root") / "session.jsonl"
    write(path, [user("one"), user("two")])
    original = Database.insert_event
    def failing(self, event):
        original(self, event)
        raise RuntimeError("simulated write failure")
    monkeypatch.setattr(Database, "insert_event", failing)
    with Database(config.db_path) as db:
        with pytest.raises(RuntimeError):
            read_file(db, path, "claude_code", claude_code.parser(config.values["claude_code"]))
        assert db.get_cursor("claude_code", str(path.resolve())) is None
        assert db.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    monkeypatch.setattr(Database, "insert_event", original)
    collect(config, "claude_code")
    with Database(config.db_path) as db:
        before = db.get_cursor("claude_code", str(path.resolve()))
    with path.open("a") as handle:
        handle.write(json.dumps(user("three")) + "\n")
    collect(config, "claude_code", replay=True)
    with Database(config.db_path) as db:
        assert db.get_cursor("claude_code", str(path.resolve())) == before
    assert collect(config, "claude_code")["claude_code"]["duplicates"] == 1
    assert len(rows(config)) == 3


def response(text="hello", identity="r1", role="user"):
    return {"timestamp": "2026-10-22T01:05:00Z", "type": "response_item", "payload": {
        "type": "message", "id": identity, "role": role,
        "content": [{"type": "input_text", "text": text}]}}


def completed(text="hello", identity="c1"):
    return {"timestamp": "2026-10-22T01:05:00Z", "type": "event_msg", "payload": {
        "type": "item_completed", "turn_id": "turn", "item": {"type": "UserMessage", "id": identity,
        "content": [{"type": "text", "text": text}]}}}


def context():
    return [{"type": "session_meta", "payload": {"id": "session", "cwd": "/project"}},
            {"type": "turn_context", "payload": {"turn_id": "turn", "cwd": "/new-project"}}]


@pytest.mark.parametrize("reverse", [False, True])
def test_channels_pair_across_runs_without_swallowing_repetition(config, reverse):
    path = config.source_path("codex", "sessions_root") / "rollout.jsonl"
    a, b = response(), completed()
    if reverse:
        a, b = b, a
    write(path, context() + [a])
    collect(config, "codex")
    with path.open("a") as handle:
        handle.write(json.dumps(b) + "\n")
        handle.write(json.dumps(response(identity="r2")) + "\n")
        handle.write(json.dumps(response(identity="r2")) + "\n")
    collect(config, "codex")
    data = rows(config)
    assert len(data) == 2
    assert all(row["project"] == "new-project" for row in data)
    collect(config, "codex", replay=True)
    assert rows(config) == data


def test_history_before_rollout_and_repeated_inputs(config):
    write(config.source_path("codex", "history_file"), [
        {"session_id": "session", "ts": 1792631100, "text": "hello"},
        {"session_id": "session", "ts": 1792631100, "text": "hello"}])
    collect(config, "codex")
    assert len(rows(config)) == 2
    write(config.source_path("codex", "sessions_root") / "rollout.jsonl", context() + [response()])
    collect(config, "codex")
    data = rows(config)
    assert len(data) == 2
    assert sum(json.loads(row["meta"])["channel"] == "history" for row in data) == 1
    collect(config, "codex")
    assert rows(config) == data


def test_redaction_before_truncation_and_disabled_sources(config):
    config.values["claude_code"]["max_assistant_chars"] = 24
    record = user(text="sk-" + "A" * 50)
    record["type"] = record["message"]["role"] = "assistant"
    write(config.source_path("claude_code", "root") / "session.jsonl", [record])
    collect(config, "claude_code")
    row = rows(config)[0]
    assert row["content"] == "[REDACTED:API_KEY]"
    assert "sk-" not in json.dumps(row)
    config.values["sources"]["claude_code"] = False
    assert collect(config, "claude_code") == {}


def test_human_text_preserves_mentions_and_mixed_input():
    assert human_text("普通提问 AGENTS.md environment_context") == "普通提问 AGENTS.md environment_context"
    assert human_text("# AGENTS.md instructions\n<INSTRUCTIONS>secret</INSTRUCTIONS>\n继续") == "继续"
    assert human_text("<system-reminder>secret</system-reminder>真实输入") == "真实输入"


def test_sidechain_path_skipped(config):
    root = config.source_path("claude_code", "root") / "subagents"
    root.mkdir()
    write(root / "agent.jsonl", [user()])
    collect(config, "claude_code")
    assert rows(config) == []
    config.values["claude_code"]["skip_sidechain"] = False
    collect(config, "claude_code")
    assert len(rows(config)) == 1


def test_invalid_records_do_not_poison_following_context(config):
    path = config.source_path("codex", "sessions_root") / "rollout.jsonl"
    invalid = response(identity="bad")
    invalid["timestamp"] = "not-a-timestamp"
    write(path, context() + [invalid, response(), {"type": "session_meta", "payload": {"id": []}},
                            {"type": "turn_context", "payload": {"cwd": 42}},
                            {"type": "response_item", "payload": {"type": "configuration_update"}}])
    report = collect(config, "codex")["codex"]
    assert report["invalid_lines"] == 2
    assert len(rows(config)) == 1
    assert "hello" not in json.dumps(report)
    with Database(config.db_path) as db:
        cursor = db.get_cursor("codex", str(path.resolve()))
        assert "hello" not in json.dumps(cursor)


def test_failed_source_file_does_not_advance_cursor(config, monkeypatch):
    path = config.source_path("claude_code", "root") / "session.jsonl"
    write(path, [user()])
    original = Path.open
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("private source")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    report = collect(config, "claude_code")["claude_code"]
    assert report["failed_files"] == 1
    assert rows(config) == []
    with Database(config.db_path) as db:
        assert db.get_cursor("claude_code", str(path.resolve())) is None


def test_mid_read_mutation_rolls_back(config):
    path = config.source_path("claude_code", "root") / "session.jsonl"
    write(path, [user()])
    original = claude_code.parser(config.values["claude_code"])
    def mutate(record, state, file, line):
        result = original(record, state, file, line)
        write(path, [user("new")])
        return result
    with Database(config.db_path) as db:
        with pytest.raises(OSError):
            read_file(db, path, "claude_code", mutate)
        assert db.get_cursor("claude_code", str(path.resolve())) is None
        assert db.connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_cli_collect_reports_partial_failure(config, capsys):
    from noesis.cli import main
    # Persist only the test paths, keeping all collection away from real sources.
    path = config.root / "config.toml"
    text = path.read_text().replace('~/.claude/projects', config.values["claude_code"]["root"])
    path.write_text(text)
    source = config.source_path("claude_code", "root") / "session.jsonl"
    source.write_text('broken\n' + json.dumps(user()) + '\n')
    assert main(["collect", "--data-dir", str(config.root), "--source", "claude_code"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["claude_code"]["inserted"] == 1
    assert report["claude_code"]["invalid_lines"] == 1
    assert main(["collect", "--data-dir", str(config.root), "--source", "claude_code"]) == 0
