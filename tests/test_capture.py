from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from noesis.config import initialize
from noesis.capture import browser_bridge
from noesis.capture.capture import create_capture,enrich_capture,annotate,compose_text
from noesis.db import Database
from noesis import queries


def test_bridge_success_fallback_and_page_change(monkeypatch):
    bundle='com.google.Chrome'
    monkeypatch.setattr(browser_bridge,'_run',lambda script,timeout:json.dumps({'url':'https://example.invalid/','title':'title','text':'body'}))
    assert browser_bridge.page(bundle,maximum=100,expected_url='https://example.invalid/')['text']=='body'
    assert browser_bridge.page(bundle,maximum=100,expected_url='https://other.invalid/')['page_text_error']=='page_changed'
    def disabled(script,timeout):
        if 'javascript' in script:raise OSError()
        return 'https://example.invalid/\x1ftitle'
    monkeypatch.setattr(browser_bridge,'_run',disabled)
    assert browser_bridge.page(bundle,maximum=100,expected_url='https://example.invalid/')['page_text_error']=='js_disabled'
    monkeypatch.setattr(browser_bridge,'_run',lambda *args:(_ for _ in ()).throw(OSError()))
    assert browser_bridge.page(bundle,maximum=100,expected_url='https://example.invalid/')['page_text_error']=='browser_unavailable'


@pytest.mark.parametrize('note_first',[True,False])
def test_capture_ocr_note_order_and_markdown(tmp_path,monkeypatch,note_first):
    config=initialize(tmp_path/'data')
    module='noesis.capture.capture'
    monkeypatch.setattr(module+'.screenshot',lambda path,**kw:path.write_bytes(b'synthetic image'))
    monkeypatch.setattr(browser_bridge,'metadata',lambda app:{'url':'https://example.invalid/?token=secret','title':'Title'})
    monkeypatch.setattr(browser_bridge,'page',lambda *args,**kw:{'title':'Title','text':'正文 sk-'+'X'*24,'selection':'选中','text_root':'ARTICLE'})
    monkeypatch.setattr(module+'.subprocess.run',lambda *args,**kw:SimpleNamespace(returncode=0,stdout=json.dumps({'text':'识别文字','ms':3})))
    result=create_capture(config,app='com.google.Chrome',background=False)
    identity=result['id']
    if note_first:annotate(config,identity,'备注 token=secret')
    enrich_capture(config,identity)
    if not note_first:annotate(config,identity,'备注 token=secret')
    with Database(config.db_path) as db:
        event=queries.capture_by_id(db.connection,identity)
        assert event.meta['ocr_status']=='done' and '备注' in event.meta['note']
        assert event.importance=='high'
        text=(config.root/Path(event.meta['screenshot']).with_suffix('.md')).read_text()
        for value in ('选中','正文','识别文字','备注','![[captures/'):
            assert value in text
        assert 'secret' not in text and 'sk-' not in text
    # Re-running a successful OCR job does not append the text again.
    enrich_capture(config,identity)
    with Database(config.db_path) as db:
        assert queries.capture_by_id(db.connection,identity).content.count('识别文字')==1


def test_failed_ocr_retains_capture_and_cancel_cleans_placeholder(tmp_path,monkeypatch):
    config=initialize(tmp_path/'data')
    module='noesis.capture.capture'
    monkeypatch.setattr(module+'.screenshot',lambda path,**kw:path.write_bytes(b'synthetic'))
    result=create_capture(config,background=False)
    monkeypatch.setattr(module+'.subprocess.run',lambda *args,**kw:SimpleNamespace(returncode=1,stdout=''))
    assert enrich_capture(config,result['id'])['status']=='failed'
    with Database(config.db_path) as db:
        assert queries.capture_by_id(db.connection,result['id'])
    monkeypatch.setattr(module+'.screenshot',lambda *args,**kw:(_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):create_capture(config,region=True,background=False)
    assert len(list((config.root/'captures').rglob('*.png')))==1


def test_text_sections_and_limit():
    text,sections=compose_text('选中','正文正文','OCR',5)
    assert 'truncated' in text
    assert all(0<=section['start']<=section['end']<=len(text) for section in sections)


def test_native_vision_ocr(tmp_path):
    import sys,shutil,subprocess
    if sys.platform!='darwin' or not shutil.which('swiftc'):
        pytest.skip('Apple Vision requires macOS and swiftc')
    root=Path(__file__).resolve().parents[1]
    binary=tmp_path/'noesis-ocr'
    subprocess.run(['swiftc','-O',str(root/'noesis/capture/ocr/ocr.swift'),'-o',str(binary)],check=True,capture_output=True,timeout=60)
    result=subprocess.run([str(binary),str(root/'tests/fixtures/ocr_sample.png')],check=True,capture_output=True,text=True,timeout=30)
    data=json.loads(result.stdout)
    assert 'NOESIS' in data['text'] and '中文识别' in data['text']
    assert all(len(line['bbox'])==4 for line in data['lines']) and not data['uniform']
