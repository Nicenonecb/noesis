"""Shared reads for CLI, daily rendering and a future local API.

Intervals are [start, end), always timezone aware. Search treats input as a
literal substring, never as FTS syntax. Short strings use escaped LIKE.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import re
from zoneinfo import ZoneInfo

from .models import Event, Session, SearchHit, DomainStat, ProjectTime, SourceStats, Stats, SOURCE_KINDS, utc_timestamp
from .timeutils import day_range


def _interval(start, end):
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ValueError("查询时间必须是带时区的 datetime。")
    a, b = utc_timestamp(start), utc_timestamp(end)
    if a >= b:
        raise ValueError("查询开始时间必须早于结束时间。")
    return a, b


def _filter(clauses, params, column, values):
    if values is not None:
        values = [values] if isinstance(values, str) else list(values)
        clauses.append(f"{column} IN ({','.join('?' for _ in values)})" if values else "0")
        params.extend(values)


def _event(row):
    values = dict(row)
    return Event(**{key: values[key] for key in (
        "source", "kind", "ts", "session_id", "project", "title", "content", "url", "raw_ref", "importance"
    )}, source_id=values.get("source_id") or values["id"],
        meta=json.loads(values["meta"]), _stored_id=values["id"])


def _session(row):
    values = dict(row)
    values.pop("id", None)
    return Session(**values)


def get_events(conn, *, start, end, sources=None, kinds=None, projects=None, limit=None, offset=0):
    params = list(_interval(start, end))
    clauses = ["ts >= ?", "ts < ?"]
    for column, values in (("source", sources), ("kind", kinds), ("project", projects)):
        _filter(clauses, params, column, values)
    if (limit is not None and limit < 0) or offset < 0:
        raise ValueError("limit 和 offset 不能为负数。")
    params.extend([-1 if limit is None else limit, offset])
    return [_event(row) for row in conn.execute(
        f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY ts,rowid LIMIT ? OFFSET ?", params)]


def get_sessions(conn, *, start, end, source=None):
    a, b = _interval(start, end)
    clauses, params = ["ended_at >= ?", "started_at < ?"], [a, b]
    _filter(clauses, params, "source", source)
    return [_session(row) for row in conn.execute(
        f"SELECT * FROM sessions WHERE {' AND '.join(clauses)} ORDER BY started_at,id", params)]


def get_session_events(conn, session_id, *, source=None):
    """Accept a sessions.id hash or an original ID; source disambiguates originals."""
    row = conn.execute("SELECT source,session_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row:
        source, session_id = row["source"], row["session_id"]
    clauses, params = ["session_id=?"], [session_id]
    _filter(clauses, params, "source", source)
    return [_event(row) for row in conn.execute(
        f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY ts,rowid", params)]


def get_event(conn, event_id):
    row = conn.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
    return _event(row) if row else None


def all_events(conn):
    return [_event(row) for row in conn.execute('SELECT * FROM events ORDER BY ts,rowid')]


def legacy_fragment_ids(conn, event):
    return [row[0] for row in conn.execute(
        'SELECT id FROM events WHERE source=? AND raw_ref=? AND id<>?',
        (event.source, event.raw_ref, event.id))]


def session_record(conn, source, session_id):
    row = conn.execute('SELECT * FROM sessions WHERE source=? AND session_id=?', (source, session_id)).fetchone()
    return _session(row) if row else None


def session_cwds(conn):
    return [row[0] for row in conn.execute('SELECT DISTINCT cwd FROM sessions WHERE cwd IS NOT NULL')]


def get_repos(conn, *, enabled=None):
    query='SELECT * FROM repos'
    params=()
    if enabled is not None:
        query+=' WHERE enabled=?'
        params=(int(enabled),)
    return [dict(row) for row in conn.execute(query+' ORDER BY path',params)]


def project_rows(conn):
    return [(row['id'], json.loads(row['meta']).get('cwd')) for row in conn.execute(
        "SELECT id,meta FROM events WHERE source IN ('claude_code','codex')")]


def browser_visits(conn, kind, cursor):
    if kind=='chromium':
        sql='''SELECT v.id,v.visit_time,v.transition,v.visit_duration,v.from_visit,u.url,u.title
               FROM visits v JOIN urls u ON u.id=v.url
               WHERE v.visit_time>? OR (v.visit_time=? AND v.id>?) ORDER BY v.visit_time,v.id'''
    else:
        sql='''SELECT hv.id,hv.visit_time,hv.title,hi.url FROM history_visits hv
               JOIN history_items hi ON hi.id=hv.history_item
               WHERE hv.visit_time>? OR (hv.visit_time=? AND hv.id>?) ORDER BY hv.visit_time,hv.id'''
    return conn.execute(sql,(cursor['time'],cursor['time'],cursor['id']))


def get_captures(conn, *, start, end):
    return get_events(conn, start=start, end=end, sources=["capture"], kinds=["capture"])


def capture_by_id(conn, identity):
    row=conn.execute("SELECT * FROM events WHERE source='capture' AND source_id=?",(identity,)).fetchone()
    return _event(row) if row else None


def _snippet(event, q):
    for text in (event.title or "", event.content, event.url or ""):
        match = re.search(re.escape(q), text, re.IGNORECASE)
        if match:
            left, right = max(0, match.start() - 60), min(len(text), match.end() + 100)
            return (("…" if left else "") + text[left:match.start()] + "[" + match.group() + "]"
                    + text[match.end():right] + ("…" if right < len(text) else ""))
    return event.content[:160]


def search(conn, q, *, limit=50, sources=None):
    q = q.strip()
    if not q or limit == 0:
        return []
    if limit < 0 or "\x00" in q:
        raise ValueError("搜索参数无效。")
    clauses, params = [], []
    if len(q) >= 3:
        table = "events e JOIN events_fts ON events_fts.rowid=e.rowid"
        clauses.append("events_fts MATCH ?")
        params.append('"' + q.replace('"', '""') + '"')
        order = "bm25(events_fts),e.ts DESC,e.id"
    else:
        table = "events e"
        value = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(e.title LIKE ? ESCAPE '\\' OR e.content LIKE ? ESCAPE '\\' OR e.url LIKE ? ESCAPE '\\')")
        params.extend([value] * 3)
        order = "e.ts DESC,e.id"
    _filter(clauses, params, "e.source", sources)
    params.append(limit)
    rows = conn.execute(f"SELECT e.* FROM {table} WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?", params)
    return [SearchHit(event, _snippet(event, q)) for event in map(_event, rows)]


def domain_summary(conn, *, start, end):
    groups = defaultdict(list)
    for event in get_events(conn, start=start, end=end, sources=["browser_history"]):
        if domain := event.meta.get("domain"):
            groups[domain].append(event)
    result = []
    for domain, events in groups.items():
        duration = 0.0
        pages = {}
        for event in events:
            seconds = event.meta.get("duration_seconds", event.meta.get("visit_duration", 0))
            if isinstance(seconds, (int, float)) and math.isfinite(seconds):
                duration += max(0, seconds)
            if event.url:
                pages[event.url] = {"url": event.url, "title": event.title}
        result.append(DomainStat(domain, len(events), duration, list(pages.values())[:3]))
    return sorted(result, key=lambda item: (-item.visits, item.domain))


def project_time(conn, *, start, end):
    """Estimate activity inside the interval, excluding browser visits.

    Consecutive gaps <= 15 minutes count as activity. Each disconnected segment
    adds two minutes. Round once per project to the nearest five minutes (half
    up). A single event therefore rounds to zero. Midnight is clipped by the
    query interval; no time is inferred from events outside that interval.
    """
    groups = defaultdict(list)
    for event in get_events(conn, start=start, end=end, sources=["claude_code", "codex", "git", "capture"]):
        if event.project:
            groups[event.project].append(datetime.fromisoformat(event.ts))
    result = []
    for project, times in groups.items():
        seconds = 120
        for before, after in zip(times, times[1:]):
            gap = (after - before).total_seconds()
            seconds += gap if gap <= 900 else 120
        result.append(ProjectTime(project, int((seconds + 150) // 300) * 5))
    return sorted(result, key=lambda item: (-item.minutes, item.project))


def stats(conn, *, tz=ZoneInfo("UTC"), now=None):
    now = now or datetime.now(timezone.utc)
    utc_timestamp(now)
    if isinstance(tz, str):
        tz = ZoneInfo(tz)
    start, end = day_range(now.astimezone(tz).date(), tz)
    totals = dict(conn.execute("SELECT source,count(*) FROM events GROUP BY source"))
    today = dict(conn.execute(
        "SELECT source,count(*) FROM events WHERE created_at>=? AND created_at<? GROUP BY source",
        (utc_timestamp(start), utc_timestamp(end))))
    result = []
    for source in SOURCE_KINDS:
        row = conn.execute("SELECT * FROM ingest_runs WHERE source=? ORDER BY started_at DESC,id DESC LIMIT 1",
                           (source,)).fetchone()
        result.append(SourceStats(source, totals.get(source, 0), today.get(source, 0), dict(row) if row else None))
    return Stats(result)


def session_summaries(conn, *, source=None):
    """Derive counts from stored events, so retries and history removal stay exact.

    M1.0 uses the first user message for the title. Parser-provided titles and
    empty sessions are added in M1.1/M1.2; preserve explicit existing titles.
    """
    clauses, params = ["source IN ('claude_code','codex')", "session_id IS NOT NULL"], []
    _filter(clauses, params, "source", source)
    rows = conn.execute(f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY ts,rowid", params)
    groups = defaultdict(list)
    for event in map(_event, rows):
        groups[(event.source, event.session_id)].append(event)
    for (name, identity), events in groups.items():
        first = next((event for event in events if event.kind == "user_msg"), events[0])
        context = next((event for event in reversed(events) if event.meta.get("cwd")), events[-1])
        # A history fallback is not the canonical raw conversation path.
        raw = next((event for event in events if event.meta.get("channel") != "history"), events[0]).raw_ref
        counts = Counter(event.kind for event in events)
        existing = conn.execute("SELECT title FROM sessions WHERE source=? AND session_id=?", (name, identity)).fetchone()
        yield Session(name, identity, events[0].ts, events[-1].ts, context.project, context.meta.get("cwd"),
                      existing[0] if existing and existing[0] else first.content[:60],
                      counts["user_msg"], counts["assistant_msg"], raw.rsplit(":", 1)[0])


def history_matches(conn):
    """Pair history copies within five seconds, preserving repeated inputs.

    Persisted match IDs on main events prevent a later pass from consuming the
    same main occurrence twice when earlier history rows have been removed.
    """
    groups = defaultdict(list)
    history = []
    for row in conn.execute("SELECT * FROM events WHERE source='codex' AND kind='user_msg' ORDER BY ts,rowid"):
        event = _event(row)
        key = (event.meta.get('session_hash'), event.meta.get('text_prefix_hash', event.meta.get('text_hash')))
        if event.meta.get('channel') == 'history':
            history.append((event, key))
        else:
            groups[key].append(event)
    matches, used = [], set()
    for event, key in history:
        candidates = groups[key]
        previous = next((main for main in candidates if event.id in main.meta.get('history_matches', [])), None)
        if previous:
            matches.append((event.id, previous.id))
            continue
        eligible = [main for main in candidates if main.id not in used and not main.meta.get('history_matches')
                    and abs((datetime.fromisoformat(main.ts) - datetime.fromisoformat(event.ts)).total_seconds()) <= 5]
        if eligible:
            main = min(eligible, key=lambda item: (abs((datetime.fromisoformat(item.ts) - datetime.fromisoformat(event.ts)).total_seconds()), item.id))
            matches.append((event.id, main.id))
            used.add(main.id)
    return matches
