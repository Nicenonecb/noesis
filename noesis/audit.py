"""Redaction audit reports locations only; repairs derived Markdown from storage."""

from dataclasses import replace
from datetime import date,datetime
import difflib
from pathlib import Path

from . import queries
from .db import Database
from .redact import redact,redact_value
from .runtime import collection_lock
from .capture.render import render_capture
from .files import atomic_write
from .render.daily import write_day

TEXT_FIELDS=('content','title','url','raw_ref','project','session_id','source_id')


def cleaned_event(event):
    changes={name:redact(getattr(event,name)) if getattr(event,name) is not None else None for name in TEXT_FIELDS}
    meta=redact_value(event.meta)
    if event.source=='capture' and changes['content']!=event.content:
        for section in meta.get('text_sections',[]):
            section['start']=len(redact(event.content[:section['start']]))
            section['end']=len(redact(event.content[:section['end']]))
    return replace(event,**changes,meta=meta)


def scan(config, conn):
    events=[];files=[];locations=[]
    for event in queries.all_events(conn):
        clean=cleaned_event(event)
        if clean!=event:
            events.append(clean)
            for name in (*TEXT_FIELDS,'meta'):
                if getattr(clean,name)!=getattr(event,name):locations.append(f'event:{event.id}:{name}')
    for directory in ('daily','captures'):
        for path in sorted((config.root/directory).rglob('*.md')):
            text=path.read_text();clean=redact(text)
            if clean==text:continue
            files.append((path,clean))
            for tag,a,b,c,d in difflib.SequenceMatcher(a=text.splitlines(),b=clean.splitlines(),autojunk=False).get_opcodes():
                if tag!='equal':locations.append(f'file:{path.relative_to(config.root)}:line:{a+1}')
    return events,files,locations


def audit_redaction(config, *, fix=False):
    with collection_lock(config.root),Database(config.db_path) as db:
        events,files,locations=scan(config,db.connection)
        if fix and locations:
            dates=set();captures=set()
            with db.transaction():
                for event in events:
                    db.replace_event(event)
                    dates.add(datetime.fromisoformat(event.ts).astimezone(config.timezone).date())
                    if event.source=='capture':captures.add(event.source_id)
                db.refresh_sessions()
            for path,clean in files:
                if path.parent==config.root/'daily':
                    try:dates.add(date.fromisoformat(path.stem));continue
                    except ValueError:pass
                if queries.capture_by_id(db.connection,path.stem):
                    captures.add(path.stem)
                else:atomic_write(path,clean)
            for selected in dates:
                if (config.root/'daily'/f'{selected}.md').exists():write_day(config,db.connection,selected)
            for identity in captures:render_capture(config,identity)
        remaining=scan(config,db.connection)[2] if fix and locations else locations
    return {'hits':len(locations),'locations':locations,'fixed':len(locations)-len(remaining) if fix else 0,'remaining':len(remaining)}
