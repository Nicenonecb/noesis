"""Idempotent local macOS integration; preserve user configuration and data."""

import argparse
from datetime import datetime
import io
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import shlex
import sys
import zipfile

from .config import initialize,load_config,private_directory
from .files import atomic_write

LABELS=('com.justin.noesis.collect','com.justin.noesis.daily')
MORNING_LABEL='com.justin.noesis.morning'
BEGIN='-- BEGIN NOESIS'
END='-- END NOESIS'


def launchctl(*arguments,check=True):
    return subprocess.run(['launchctl',*arguments],capture_output=True,text=True,check=check,timeout=20)


def plist(config,project,label):
    if label==MORNING_LABEL:
        return {'Label':label,'ProgramArguments':[str(morning_app(config)/'Contents/MacOS/NOESISMorning')],
                'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':30,
                'StandardOutPath':str(config.root/'logs/launchd-morning.log'),
                'StandardErrorPath':str(config.root/'logs/launchd-morning-error.log')}
    ai=config.values['digest']['enabled']
    command='collect' if label.endswith('collect') else 'morning-run' if ai else 'daily-run'
    args=[str(Path(sys.executable).resolve()),'-I',str(config.root/'bin/noesis.pyz'),command,'--data-dir',str(config.root)]
    if command=='daily-run':args+=['--catch-up','7']
    result={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(config.root),
            'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
            'StandardOutPath':str(config.root/'logs'/f'launchd-{label.rsplit(".",1)[-1]}.log'),
            'StandardErrorPath':str(config.root/'logs'/f'launchd-{label.rsplit(".",1)[-1]}-error.log')}
    if label.endswith('collect'):result.update(StartInterval=1800,RunAtLoad=True)
    elif ai:
        hour,minute=map(int,config.values['digest']['generate_after'].split(':'))
        result.update(StartCalendarInterval={'Hour':hour,'Minute':minute},StartInterval=300,RunAtLoad=True)
    else:result['StartCalendarInterval']={'Hour':23,'Minute':30}
    return result


def morning_app(config):
    return config.root/'bin/NOESIS Morning.app'


def managed_labels(config):
    return (*LABELS,MORNING_LABEL) if config.values['digest']['enabled'] else LABELS


def install_runtime(config,project):
    # launchd must not depend on a venv/checkout inside Desktop (macOS TCC).
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('__main__.py','from noesis.cli import main\nraise SystemExit(main())\n')
        for path in sorted((project/'noesis').rglob('*.py')):
            archive.write(path,path.relative_to(project).as_posix())
    bundle=config.root/'bin/noesis.pyz'
    atomic_write(bundle,output.getvalue())
    executable=config.root/'bin/noesis'
    python=Path(sys.executable).resolve()
    atomic_write(executable,'#!/bin/sh\nexec '+shlex.quote(str(python))+' -I '+shlex.quote(str(bundle))+' "$@"\n')
    executable.chmod(0o700)


def compile_morning(config,project):
    app=morning_app(config)
    private_directory(app/'Contents/MacOS')
    info={'CFBundleIdentifier':MORNING_LABEL,'CFBundleName':'NOESIS Morning',
          'CFBundleDisplayName':'NOESIS 晨报','CFBundleExecutable':'NOESISMorning',
          'CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0','CFBundleVersion':'1',
          'LSUIElement':True,'NSHighResolutionCapable':True,
          'NOESISExecutable':str(config.root/'bin/noesis'),'NOESISDataDirectory':str(config.root),
          'NOESISTimezone':config.timezone.key}
    atomic_write(app/'Contents/Info.plist',plistlib.dumps(info))
    subprocess.run(['swiftc','-O',str(project/'noesis/digest/morning.swift'),'-o',str(app/'Contents/MacOS/NOESISMorning')],
                   check=True,capture_output=True,timeout=120)
    subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,capture_output=True,timeout=30)
    subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister',
                    '-f',str(app)],check=True,capture_output=True,timeout=30)


def strip_block(text):
    return re.sub(r'(?m)^-- BEGIN NOESIS\n.*?^-- END NOESIS\n?','',text,flags=re.S)


def configure_hammerspoon(config,project):
    directory=Path.home()/'.hammerspoon'
    private_directory(directory)
    generated=config.root/'run/noesis-hammerspoon.lua'
    link=directory/'noesis.lua'
    if (link.exists() or link.is_symlink()) and not (link.is_symlink() and link.resolve()==generated):
        raise ValueError('已有 ~/.hammerspoon/noesis.lua，未覆盖。请移动该文件后重试。')
    text=(project/'hammerspoon/noesis.lua').read_text()
    text=text.replace('__NOESIS_EXECUTABLE__',json.dumps(str(config.root/'bin/noesis'),ensure_ascii=False))
    text=text.replace('__NOESIS_DATA_DIR__',json.dumps(str(config.root),ensure_ascii=False))
    text=text.replace('__NOESIS_ASK_NOTE__','true' if config.values['capture']['ask_note'] else 'false')
    atomic_write(generated,text)
    if not link.is_symlink():link.symlink_to(generated)
    init=directory/'init.lua'
    original=init.read_text() if init.exists() else ''
    block=f'{BEGIN}\nrequire("noesis")\n{END}\n'
    if block in original:return
    if original:
        backup=config.root/'backups'/f'hammerspoon-init-{datetime.now(config.timezone):%Y%m%d-%H%M%S}.lua'
        atomic_write(backup,original)
    atomic_write(init,strip_block(original).rstrip()+'\n'+block)


def install(config,project,*,load=True):
    project=project.resolve()
    domain=f'gui/{os.getuid()}'
    if load:
        for label in (*LABELS,MORNING_LABEL):
            launchctl('bootout',domain+'/'+label,check=False)
    install_runtime(config,project)
    subprocess.run(['swiftc','-O',str(project/'noesis/capture/ocr/ocr.swift'),'-o',str(config.root/'bin/noesis-ocr')],
                   check=True,capture_output=True,timeout=120)
    configure_hammerspoon(config,project)
    if config.values['digest']['enabled']:compile_morning(config,project)
    agents=Path.home()/'Library/LaunchAgents';private_directory(agents)
    if not config.values['digest']['enabled']:
        (agents/(MORNING_LABEL+'.plist')).unlink(missing_ok=True)
    for label in managed_labels(config):
        data=plist(config,project,label)
        for key in ('StandardOutPath','StandardErrorPath'):
            path=Path(data[key]);fd=os.open(path,os.O_APPEND|os.O_CREAT|os.O_WRONLY,0o600);os.close(fd)
        target=agents/(label+'.plist')
        atomic_write(target,plistlib.dumps(data,sort_keys=True))
        if load:
            launchctl('bootstrap',domain,str(target))
    return {'installed':list(managed_labels(config)),'hammerspoon':'配置已写入；安装应用并授权后重载配置'}


def uninstall(config,*,load=True):
    domain=f'gui/{os.getuid()}'
    for label in (*LABELS,MORNING_LABEL):
        if load:launchctl('bootout',domain+'/'+label,check=False)
        (Path.home()/'Library/LaunchAgents'/(label+'.plist')).unlink(missing_ok=True)
    directory=Path.home()/'.hammerspoon';link=directory/'noesis.lua'
    if link.is_symlink() and link.resolve()==config.root/'run/noesis-hammerspoon.lua':link.unlink()
    init=directory/'init.lua'
    if init.exists():
        original=init.read_text();clean=strip_block(original)
        if clean!=original:atomic_write(init,clean)
    return {'uninstalled':list((*LABELS,MORNING_LABEL)),'data_preserved':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['install','uninstall'])
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    try:
        config=initialize(args.data_dir) if args.action=='install' else load_config(args.data_dir)
        result=install(config,args.project) if args.action=='install' else uninstall(config)
        print(json.dumps(result,ensure_ascii=False))
    except subprocess.CalledProcessError as exc:
        print(json.dumps({'error':'install_command_failed','tool':Path(exc.cmd[0]).name,
                          'exit_code':exc.returncode},ensure_ascii=False))
        return 1
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print(json.dumps({'error':type(exc).__name__,'detail':'安装未完成；检查本机 Swift、launchd 与 Hammerspoon 配置冲突。'},ensure_ascii=False))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
