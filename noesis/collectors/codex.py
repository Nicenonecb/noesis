"""Codex response, completed-item and legacy channels with occurrence matching."""

from datetime import datetime, timezone
import json

from .common import UnknownRecord, fingerprint, human_text, make_event, text_content
from ..models import ToolUpdate, utc_timestamp

IGNORED = {"world_state", "token_usage_record", "compacted"}
IGNORED_ITEMS = {"Reasoning", "CommandExecution", "McpToolCall", "FileChange", "Extension",
                 "ContextCompaction", "ImageView", "WebSearch", "Plan"}
IGNORED_EVENTS = {"task_started", "task_complete", "token_count", "thread_settings_applied",
                  "turn_aborted", "agent_reasoning", "agent_reasoning_raw_content",
                  "context_compacted", "warning", "error"}
IGNORED_RESPONSES = {"reasoning", "function_call", "function_call_output", "custom_tool_call",
                     "custom_tool_call_output", "additional_tools", "web_search_call",
                     "configuration_update"}


def parser(settings):
    def parse(record, state, path, line):
        kind, payload = record.get("type"), record.get("payload")
        if not isinstance(payload, dict):
            return None
        if kind == "session_meta":
            session = payload.get("session_id") or payload.get("id") or path.stem
            cwd = payload.get("cwd")
            if not isinstance(session, str) or (cwd is not None and not isinstance(cwd, str)):
                raise ValueError("context")
            state["session"] = session
            state["session_hash"] = fingerprint(state["session"])
            state["cwd"] = payload.get("cwd")
            state['cli_version'] = payload.get('cli_version')
            if stamp := payload.get('timestamp', record.get('timestamp')):
                state['started_at'] = state['ended_at'] = utc_timestamp(stamp)
            return None
        if kind == "turn_context":
            if payload.get("cwd") is not None and not isinstance(payload["cwd"], str):
                raise ValueError("cwd")
            state["cwd"] = payload.get("cwd", state.get("cwd"))
            state["turn"] = payload.get("turn_id", state.get("turn", ""))
            return None
        if kind == 'response_item' and payload.get('type') in {'function_call', 'custom_tool_call'}:
            if not state.get('last_assistant_id'):
                return None
            arguments = payload.get('arguments', payload.get('input', {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            detail = next((arguments[key] for key in ('cmd','command','file_path','path') if key in arguments), '')
            if isinstance(detail, list):
                detail = ' '.join(str(part) for part in detail)
            tool = {'name': str(payload.get('name', 'shell')), 'summary': str(detail)[:200]}
            return ToolUpdate(state['last_assistant_id'], fingerprint(str(payload.get('call_id') or record)),
                              tool, utc_timestamp(record['timestamp']))
        channel, role, phase, content = "", "", "", ""
        if kind == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            channel, content = "response", payload.get("content")
            phase = payload.get("phase") or ""
        elif kind == "event_msg" and payload.get("type") == "item_completed":
            item = payload.get("item")
            if not isinstance(item, dict):
                return None
            role = {"UserMessage": "user", "AgentMessage": "assistant"}.get(item.get("type"))
            if role is None and item.get("type") not in IGNORED_ITEMS:
                raise UnknownRecord()
            channel, content = "completed", item.get("content")
            phase = item.get("phase") or ""
        elif kind == "event_msg" and payload.get("type") in {"user_message", "agent_message"}:
            role = "user" if payload["type"] == "user_message" else "assistant"
            channel, content = "legacy", payload.get("message")
        if role not in {"user", "assistant"}:
            if kind == "response_item" and payload.get("type") not in IGNORED_RESPONSES | {"message"}:
                raise UnknownRecord()
            if kind == "event_msg" and payload.get("type") not in IGNORED_EVENTS | {"item_completed"}:
                raise UnknownRecord()
            if kind not in IGNORED | {"response_item", "event_msg"}:
                raise UnknownRecord()
            return None
        text = text_content(content)
        text = human_text(text) if role == "user" else text.strip()
        if role == 'user' and any(text.startswith(prefix) for prefix in settings.get('injected_prefixes', [])):
            return None
        if not text:
            return None
        session = state.get("session", path.stem)
        session_hash = state.get("session_hash", fingerprint(session))
        # Pair the Nth equal message from each channel within a turn. Repeated
        # messages within one channel remain distinct; no global text dedup.
        turn = payload.get("turn_id") or state.get("turn") or ""
        match_key = fingerprint(f"{session_hash}|{turn}|{role}|{text}")
        counter_key = f"{channel}:{match_key}"
        counters = state.setdefault("occurrences", {})
        message_id = (payload.get("item", {}) if channel == "completed" else payload).get("id")
        seen_key = fingerprint(f"{channel}|{message_id}|{text}") if message_id else None
        seen = state.setdefault("seen", {})
        if seen_key and seen_key in seen:
            return None
        occurrence = counters.get(counter_key, 0) + 1
        event = make_event("codex", f"{match_key}:{occurrence}", role, record["timestamp"],
                           text, session, state.get("cwd"), path, line,
                           settings["max_assistant_chars"],
                           {"channel": channel, "phase": phase, "turn_id": turn,
                            'cli_version': state.get('cli_version')})
        stamp = utc_timestamp(record['timestamp'])
        state['started_at'] = min(state.get('started_at', stamp), stamp)
        state['ended_at'] = max(state.get('ended_at', stamp), stamp)
        if role == 'assistant' and event:
            state['last_assistant_id'] = event.id
        counters[counter_key] = occurrence
        if seen_key:
            seen[seen_key] = True
        return event
    return parse


def history_parser(settings):
    def parse(record, state, path, line):
        session, seconds, text = record["session_id"], record["ts"], record["text"]
        if not isinstance(session, str) or type(seconds) is not int or not isinstance(text, str):
            raise ValueError("history")
        text = human_text(text)
        if not text:
            return None
        timestamp = datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        key = fingerprint(f"{session}|{timestamp}|{text}")
        counters = state.setdefault("occurrences", {})
        occurrence = counters.get(key, 0) + 1
        event = make_event("codex", f"history:{key}:{occurrence}", "user", timestamp, text,
                           session, None, path, line, settings["max_assistant_chars"],
                           {"channel": "history", "history_occurrence": occurrence, 'from_history': True})
        counters[key] = occurrence
        return event
    return parse


def reconcile_history(db):
    """Match one history occurrence per session message within five seconds.

    Re-run after every pass so a later-arriving rollout can replace history-only
    input. Persisted pairings prevent a main occurrence being reused on retries.
    """
    from ..queries import history_matches, get_event
    matches = history_matches(db.connection)
    with db.transaction():
        for history_id, main_id in matches:
            event = get_event(db.connection, main_id)
            db.update_event_meta(main_id, {'history_matches': sorted(set(event.meta.get('history_matches', []) + [history_id]))})
        db.delete_events([history for history, main in matches])
    return len(matches)
