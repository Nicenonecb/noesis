"""Browser visits from private SQLite copies, normalized before storage."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
import glob
import hashlib
import ipaddress
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .. import queries
from ..models import Event, utc_timestamp
from ..redact import clean_url
from ..sqlite_snapshot import history_snapshot

TRANSITIONS={0:'link',1:'typed',2:'auto_bookmark',5:'generated',6:'auto_toplevel',7:'form_submit',8:'reload',9:'keyword',10:'keyword_generated'}


def expand_braces(pattern):
    match=re.search(r'\{([^{}]+)\}',pattern)
    if not match:
        return [pattern]
    return [expanded for option in match[1].split(',')
            for expanded in expand_braces(pattern[:match.start()]+option+pattern[match.end():])]


def profiles(config):
    seen=set()
    for profile in config.values['browser']['profiles_glob']:
        if profile['name'] not in config.values['browser']['enabled']:
            continue
        for pattern in expand_braces(str(Path(profile['glob']).expanduser())):
            # Literal paths retain permission failures for explicit diagnostics.
            paths=glob.glob(pattern) if glob.has_magic(pattern) else [pattern]
            for value in paths:
                path=Path(value)
                key=(profile['name'],str(path))
                if key not in seen:
                    seen.add(key)
                    yield profile,path


def visit_event(row, profile, path, settings):
    url=row['url'] or ''
    parsed=urlsplit(url)
    host=(parsed.hostname or '').lower()
    if parsed.scheme not in {'http','https'} or not host or host=='localhost':
        return None
    try:
        if ipaddress.ip_address(host).is_loopback:
            return None
    except ValueError:
        pass  # A DNS hostname is not an IP literal.
    if any(fnmatch(host,pattern.lower()) for pattern in settings['blacklist_domains']):
        return None
    if any(re.search(pattern,url) for pattern in settings['blacklist_url_regex']):
        return None
    chromium=profile['kind']=='chromium'
    transition=(row['transition'] or 0)&0xFF if chromium else None
    if transition in {3,4}:
        return None
    epoch=datetime(1601 if chromium else 2001,1,1,tzinfo=timezone.utc)
    delta=timedelta(microseconds=row['visit_time']) if chromium else timedelta(seconds=row['visit_time'])
    title=row['title'] or parsed.path or host
    normal=clean_url(url,tracking=True)
    identity=f"{profile['name']}:{hashlib.sha256(str(path).encode()).hexdigest()}:{row['id']}:{row['visit_time']}"
    return Event('browser_history',identity,'visit',epoch+delta,content=title,title=title,url=normal,
                 raw_ref=f'{path}:{row["id"]}',meta={'browser':profile['name'],'profile':path.parent.name,
                 'url_raw':clean_url(url),'domain':host.removeprefix('www.'),'repeat':0,
                 'duration_seconds':max(0,(row['visit_duration'] or 0)/1e6) if chromium else 0,
                 'transition':TRANSITIONS.get(transition,'unknown') if chromium else 'unknown'})


def collect(ctx, *, backfill=None, dry_run=False):
    db=ctx.db;config=ctx.config;counts=Counter();issues=[]
    start=datetime.now(timezone.utc)-backfill if isinstance(backfill,timedelta) else None
    for profile,path in profiles(config):
        browser=profile['name'];key=str(path)
        try:
            # Missing optional browsers are not warnings; permission denial is.
            path.stat()
        except FileNotFoundError:
            continue
        except OSError:
            counts['failed_files']+=1
            issues.append({'browser':browser,'profile':path.parent.name,'error':'permission_denied'})
            continue
        try:
            cursor=None if backfill is not None else db.get_cursor('browser_history',key)
            cursor=cursor or {'time':0,'id':0,'last':None}
            last=cursor.get('last')
            with history_snapshot(path) as connection:
                rows=queries.browser_visits(connection,profile['kind'],cursor)
                while batch:=rows.fetchmany(500):
                    batch_counts=Counter()
                    with db.transaction():
                        for row in batch:
                            cursor['time'],cursor['id']=row['visit_time'],row['id']
                            try:
                                event=visit_event(row,profile,path,config.values['browser'])
                            except (ValueError,OverflowError,TypeError):
                                batch_counts['invalid_lines']+=1;last=None;continue
                            if event is None or (start and event.ts<utc_timestamp(start)):
                                batch_counts['skipped']+=1;last=None;continue
                            if last and last['url']==event.url and 0<=(datetime.fromisoformat(event.ts)-datetime.fromisoformat(last['ts'])).total_seconds()<=60:
                                previous=queries.get_event(db.connection,last['id'])
                                if previous:
                                    db.update_event_meta(previous.id,{'repeat':previous.meta.get('repeat',0)+1,
                                        'duration_seconds':previous.meta.get('duration_seconds',0)+event.meta['duration_seconds']})
                                    batch_counts['merged']+=1
                                    last['ts']=event.ts
                                    continue
                            inserted=db.insert_event(event)
                            if not inserted and backfill is not None:
                                db.update_event_meta(event.id,{'repeat':0,'duration_seconds':event.meta['duration_seconds']})
                            batch_counts['inserted' if inserted else 'duplicates']+=1
                            last={'id':event.id,'url':event.url,'ts':event.ts}
                        cursor['last']=last
                        db.set_cursor('browser_history',key,cursor)
                    counts.update(batch_counts)
            counts['files']+=1;counts['completed_files']+=1
            issues.append({'browser':browser,'profile':path.parent.name,'status':'ok'})
        except (OSError,sqlite3.Error):
            counts['failed_files']+=1
            issues.append({'browser':browser,'profile':path.parent.name,'error':'history_unreadable'})
    return counts,issues
