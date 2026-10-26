from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from noesis import queries
from noesis.db import Database
from noesis.models import Event, Session, utc_timestamp
from noesis.timeutils import day_range


@pytest.fixture
def db():
    with Database(":memory:") as database:
        yield database


def event(identity="one", **kw):
    return Event(**(dict(source="codex", source_id=identity, kind="user_msg", ts="2026-10-22T09:00:00+08:00",
                        content="中文数据库 Python 索引", session_id="session", project="demo") | kw))


@pytest.fixture
def interval():
    return dict(zip(("start", "end"), day_range(date(2026, 10, 22), "Asia/Shanghai")))


def test_get_events_filters_order_pagination_identity(db, interval):
    a = event("a", ts=interval["start"])
    b = event("b")
    c = event("c", source="git", kind="commit", project="other", ts=interval["end"] - timedelta(seconds=1))
    db.upsert_events([c, b, a, event("excluded", ts=interval["end"])])
    assert [e.id for e in queries.get_events(db.connection, **interval)] == [a.id, b.id, c.id]
    assert queries.get_events(db.connection, **interval, sources=[] ) == []
    assert [e.id for e in queries.get_events(db.connection, **interval, sources="git", projects=["other"], kinds=["commit"])] == [c.id]
    assert [e.id for e in queries.get_events(db.connection, **interval, limit=1, offset=1)] == [b.id]
    assert queries.get_events(db.connection, **interval, limit=0) == []
    for invalid in [dict(limit=-1), dict(offset=-1), dict(start=datetime(2026, 10, 22)), dict(end=interval["start"])]:
        with pytest.raises(ValueError):
            queries.get_events(db.connection, **(interval | invalid))


@pytest.mark.parametrize("q", ["数据库", "数据", "中", "Python", "python", "中文数据库"])
def test_search_chinese_short_and_english_highlights(db, q):
    item = event()
    db.insert_event(item)
    hits = queries.search(db.connection, q)
    assert len(hits) == 1 and hits[0].event.id == item.id
    assert "[" in hits[0].snippet and "]" in hits[0].snippet


def test_search_literal_syntax_sources_title_url_and_limits(db):
    db.upsert_events([event("text", content='使用 "abc" OR x_% 与 C++'),
                      event("title", title="标题可检索", content="other"),
                      event("url", source="capture", kind="capture", url="https://example.invalid/needle", content="other")])
    for q in ['"abc"', "OR", "_%", "C++", "标题可检索", "needle"]:
        assert len(queries.search(db.connection, q)) == 1
    assert queries.search(db.connection, "%")
    assert queries.search(db.connection, "not-here OR Python") == []
    assert queries.search(db.connection, "needle", sources=["codex"]) == []
    assert len(queries.search(db.connection, "other", limit=1)) == 1
    assert queries.search(db.connection, " ") == []
    assert queries.search(db.connection, "other", sources=[]) == []
    assert queries.search(db.connection, "other", limit=0) == []
    with pytest.raises(ValueError):
        queries.search(db.connection, "other", limit=-1)


def test_sessions_cross_midnight_and_source_disambiguation(db, interval):
    db.upsert_events([event("old", ts=interval["start"] - timedelta(minutes=1)), event("new"),
                      event("cc", source="claude_code")])
    db.refresh_sessions()
    sessions = queries.get_sessions(db.connection, **interval)
    assert len(sessions) == 2
    codex = queries.get_sessions(db.connection, **interval, source="codex")[0]
    assert codex.n_user == 2 and codex.n_assistant == 0
    assert codex.title == "中文数据库 Python 索引"
    assert len(queries.get_session_events(db.connection, codex.id)) == 2
    assert len(queries.get_session_events(db.connection, "session", source="claude_code")) == 1
    assert queries.get_session_events(db.connection, "missing") == []
    assert queries.get_sessions(db.connection, start=interval["end"], end=interval["end"] + timedelta(days=1)) == []


def test_capture_and_domain_summary(db, interval):
    capture = event("capture", source="capture", kind="capture")
    db.insert_event(capture)
    assert [e.id for e in queries.get_captures(db.connection, **interval)] == [capture.id]
    for i in range(5):
        db.insert_event(event(str(i), source="browser_history", kind="visit", url=f"https://example.invalid/{i}",
                              title=str(i), meta={"domain": "example.invalid", "duration_seconds": 3}))
    db.insert_event(event("other", source="browser_history", kind="visit", meta={"domain": "other.invalid", "duration_seconds": -3}))
    summary = queries.domain_summary(db.connection, **interval)
    assert [(s.domain, s.visits, s.duration_seconds) for s in summary] == [("example.invalid", 5, 15), ("other.invalid", 1, 0)]
    assert len(summary[0].pages) == 3


@pytest.mark.parametrize("minutes,expected", [([0], 0), ([0, 15], 15), ([0, 16], 5), ([0, 10, 20], 20), ([0, 0], 0)])
def test_project_time_gaps_and_rounding(db, interval, minutes, expected):
    for i, minute in enumerate(minutes):
        db.insert_event(event(str(i), ts=interval["start"] + timedelta(minutes=minute)))
    db.insert_event(event("previous", ts=interval["start"] - timedelta(minutes=1)))
    db.insert_event(event("next", ts=interval["end"]))
    db.insert_event(event("web", source="browser_history", kind="visit", ts=interval["start"] + timedelta(minutes=14)))
    db.insert_event(event("unassigned", project=None))
    result = queries.project_time(db.connection, **interval)
    assert [(r.project, r.minutes) for r in result] == [("demo", expected)]


def test_stats_counts_created_today_and_latest_run(db):
    now = datetime(2026, 10, 22, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    db.upsert_events([event("a"), event("b")])
    db.connection.execute("UPDATE events SET created_at=? WHERE id=?", (utc_timestamp(now), event("a").id))
    db.connection.execute("UPDATE events SET created_at=? WHERE id=?", (utc_timestamp(now - timedelta(minutes=2)), event("b").id))
    db.connection.commit()
    run_id = db.start_run("codex")
    db.finish_run(run_id, status="partial", inserted=2, skipped=3, warnings=4)
    result = queries.stats(db.connection, tz="Asia/Shanghai", now=now)
    codex = next(s for s in result.sources if s.source == "codex")
    assert (codex.total, codex.today_inserted) == (2, 1)
    assert codex.last_run["status"] == "partial" and codex.last_run["warnings"] == 4
    empty = next(s for s in result.sources if s.source == "git")
    assert empty.total == 0 and empty.last_run is None


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_day_range_handles_dst(day, hours):
    start, end = day_range(day, "America/New_York")
    assert (end - start).total_seconds() == hours * 3600
    assert start.tzinfo == timezone.utc
    with pytest.raises(ValueError):
        day_range(datetime.now(), "UTC")
