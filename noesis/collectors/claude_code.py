"""Claude Code messages, excluding tool results, reasoning and sidechains."""

from .common import UnknownRecord, make_event, text_content

IGNORED = {"queue-operation", "attachment", "last-prompt", "file-history-snapshot",
           "file-history-delta", "atis-latch", "api-request-shape", "api-request-blob",
           "api-request", "custom-title", "agent-name", "system", "cost-state", "mode",
           "summary", "progress"}


def parser(settings):
    def parse(record, state, path, line):
        role = record.get("type")
        if role not in {"user", "assistant"}:
            if role not in IGNORED:
                raise UnknownRecord()
            return None
        if record.get("isMeta") or (settings["skip_sidechain"] and
                                    (record.get("isSidechain") or "subagents" in path.parts)):
            return None
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != role:
            return None
        session = record.get("sessionId") or path.stem
        identity = record["uuid"]
        if not isinstance(identity, str) or not identity:
            raise ValueError("uuid")
        metadata = {"git_branch": record.get("gitBranch")}
        blocks = message.get("content")
        if isinstance(blocks, list):
            metadata["tools"] = [b["name"] for b in blocks if isinstance(b, dict)
                                 and b.get("type") == "tool_use" and isinstance(b.get("name"), str)]
        return make_event("claude_code", f"{session}:{identity}", role, record["timestamp"],
                          text_content(blocks), session, record.get("cwd"), path, line,
                          settings["max_assistant_chars"], metadata)
    return parse
