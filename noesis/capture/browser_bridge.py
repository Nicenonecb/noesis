"""AppleScript access to an explicitly selected browser; no HTTP requests."""

import json
import hashlib
import subprocess
from ..redact import clean_url

APPS={'com.google.Chrome':('Google Chrome','active tab of front window','title'),
      'company.thebrowser.Browser':('Arc','active tab of front window','title'),
      'com.apple.Safari':('Safari','current tab of front window','name')}


def _run(script,timeout):
    result=subprocess.run(['osascript','-e',script],capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        raise OSError('AppleScript failed')
    return result.stdout.strip()


def metadata(bundle, *, timeout=.35):
    if bundle not in APPS:
        return {}
    app,tab,title=APPS[bundle]
    script=f'tell application "{app}" to return (URL of {tab}) & (ASCII character 31) & ({title} of {tab})'
    try:
        url,name=_run(script,timeout).split('\x1f',1)
        return {'url':url,'title':name}
    except (OSError,ValueError,subprocess.SubprocessError):
        return {'page_text_error':'browser_unavailable'}


def page(bundle, *, maximum, expected_url, expected_hash=None):
    """Only enrich the page captured before the note dialog, not a later tab."""
    if bundle not in APPS:
        return {}
    if not expected_url:
        return {'page_text_error':'browser_unavailable'}
    app,tab,title=APPS[bundle]
    js='''(() => { const pick=document.querySelector('article, main, .Post-RichText, .RichContent-inner, .QuestionAnswer-content');
      const root=pick||document.body; return JSON.stringify({url:location.href,title:document.title,
      selection:String(window.getSelection()||''),text:root.innerText.slice(0,MAX),
      text_root:pick?(pick.className||pick.tagName):'body',description:document.querySelector('meta[name=description]')?.content||'',
      lang:document.documentElement.lang||''}); })()'''.replace('MAX',str(int(maximum)))
    quoted=json.dumps(js,ensure_ascii=False)
    if bundle=='com.apple.Safari':
        script=f'tell application "{app}" to do JavaScript {quoted} in {tab}'
    elif bundle=='company.thebrowser.Browser':
        script=f'tell application "{app}" to tell front window to tell active tab to execute javascript {quoted}'
    else:
        script=f'tell application "{app}" to execute {tab} javascript {quoted}'
    try:
        result=json.loads(_run(script,3))
        if not isinstance(result,dict) or not all(isinstance(result.get(key,''),str) for key in ('url','title','selection','text')):
            raise ValueError('invalid browser response')
        if clean_url(result.get('url',''))!=expected_url or (expected_hash and hashlib.sha256(result['url'].encode()).hexdigest()!=expected_hash):
            return {'page_text_error':'page_changed'}
        return result
    except (OSError,ValueError,subprocess.SubprocessError):
        result=metadata(bundle,timeout=.3)
        if result.get('url') and (clean_url(result['url'])!=expected_url or (expected_hash and hashlib.sha256(result['url'].encode()).hexdigest()!=expected_hash)):
            return {'page_text_error':'page_changed'}
        result['page_text_error']='js_disabled' if result.get('url') else 'browser_unavailable'
        return result
