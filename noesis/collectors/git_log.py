"""Local repository discovery and author-filtered commit collection."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess

from ..models import Event, utc_timestamp
from .. import queries

EXCLUDED = {'node_modules','.venv','venv','Library','.cache','dist','build'}


def git(path, *arguments):
    result = subprocess.run(['git','-C',str(path),*arguments], capture_output=True, timeout=15)
    if result.returncode:
        raise OSError('git command failed')
    return result.stdout.decode('utf-8', errors='replace').strip('\n')


def repo_info(path):
    root=Path(git(path,'rev-parse','--show-toplevel')).resolve()
    common=Path(git(root,'rev-parse','--git-common-dir'))
    common=(root/common).resolve() if not common.is_absolute() else common.resolve()
    # Linked worktrees use the primary .git directory. Prefer its canonical root.
    if common.name=='.git' and common.parent.exists():
        root=common.parent
    return {'path':str(root),'name':root.name,'common_dir':str(common)}


def discover(config, db):
    candidates=[(Path(path).expanduser(),'config') for path in config.values['git']['repos']]
    for raw in config.values['git']['scan_roots']:
        root=Path(raw).expanduser()
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root):
            path=Path(directory)
            depth=len(path.relative_to(root).parts)
            dirs[:]=[name for name in dirs if name not in EXCLUDED and not name.startswith('.') and depth<3]
            if (path/'.git').exists():
                candidates.append((path,'scan'))
                dirs[:]=[]
    if config.values['git']['discover_from_sessions']:
        candidates.extend((Path(path),'session') for path in queries.session_cwds(db.connection))
    warnings=0
    with db.transaction():
        for path,via in dict.fromkeys(candidates):
            if not path.is_dir():
                continue
            try:
                db.upsert_repo(repo_info(path),via)
            except (OSError,subprocess.SubprocessError):
                if via=='config':
                    warnings+=1
    return warnings


def authors(config, path):
    emails=set(config.values['git']['author_emails'])
    for args in (('config','--global','--get','user.email'),('config','--get','user.email')):
        try:
            email=git(path,*args).strip()
            if email:
                emails.add(email)
        except OSError:
            pass  # A missing optional Git setting returns 1.
    return sorted(emails)


def parse_log(text, repo):
    for part in text.split('\x1e')[1:]:
        header, stats=part.split('\x00',1)
        sha,author_at,commit_at,author,email,parents,refs,title,body=header.split('\x1f',8)
        files=[];insertions=deletions=0
        entries=iter(stats.lstrip('\n').split('\x00'))
        for entry in entries:
            entry=entry.lstrip('\n')
            if not entry.strip():
                continue
            added,removed,name=entry.split('\t',2)
            if not name:  # -z rename: empty path followed by old and new names.
                old=next(entries);name=next(entries)
            insertions+=int(added) if added!='-' else 0
            deletions+=int(removed) if removed!='-' else 0
            files.append(name)
        event=Event('git',sha,'commit',author_at,content=(title+'\n'+body).strip(),title=title,
                    project=repo['name'],session_id=repo['name'],raw_ref=f"{repo['path']}@{sha}",
                    meta={'repo':repo['name'],'repo_path':repo['path'],'refs':refs,
                          'is_merge':len(parents.split())>1,'files_changed':len(files),
                          'insertions':insertions,'deletions':deletions,'files':files[:50],
                          'author':author,'author_email':email,'committed_at':utc_timestamp(commit_at)})
        yield event


def collect(ctx, *, backfill=None, dry_run=False):
    config,db=ctx.config,ctx.db
    counts=Counter(discovery_warnings=discover(config,db))
    start=datetime.now(timezone.utc)-backfill if isinstance(backfill,timedelta) else None
    for repo in queries.get_repos(db.connection,enabled=True):
        try:
            emails=authors(config,repo['path'])
            if not emails:
                counts['missing_authors']+=1
                continue
            cursor=None if backfill is not None else db.get_cursor('git',repo['common_dir'])
            since=datetime.fromisoformat(cursor)-timedelta(days=1) if cursor else start
            args=['log','--all','--date-order','--fixed-strings','--no-show-signature']
            if since:
                args.append('--since='+utc_timestamp(since))
            args.extend('--author='+email for email in emails)
            args.extend(['--format=%x1e%H%x1f%aI%x1f%cI%x1f%an%x1f%ae%x1f%P%x1f%D%x1f%s%x1f%b%x00','--numstat','-z'])
            events=[event for event in parse_log(git(repo['path'],*args),repo) if event.meta['author_email'] in emails]
            watermarks=[event.meta['committed_at'] for event in events]
            if cursor:watermarks.append(cursor)
            if start:watermarks.append(utc_timestamp(start))
            maximum=max(watermarks,default=None)
            selected=[event for event in events if not start or event.ts>=utc_timestamp(start)]
            for index in range(0,max(1,len(selected)),500):
                with db.transaction():
                    added,skipped=db.upsert_events(selected[index:index+500])
                    if index+500>=len(selected) and maximum:
                        db.set_cursor('git',repo['common_dir'],maximum)
                counts['inserted']+=added;counts['duplicates']+=skipped
            counts['completed_files']+=1
            counts['files']+=1
        except (OSError,subprocess.SubprocessError,ValueError,StopIteration):
            counts['failed_files']+=1
    return counts,[]
