import re
from html.parser import HTMLParser

import pytest

from noesis.config import initialize
from noesis.digest.render import write_briefing
from noesis.render.markdown import render_markdown


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.text.append(value)


def report(*, source='codex', title='', text=''):
    return {'source_day': '2026-10-25', 'delivery_day': '2026-10-26', 'model': 'synthetic',
            'source_counts': {source: 1}, 'source_health': {}, 'omitted_events': 0,
            'evidence': [{'id': 'E1', 'source': source, 'project': '', 'time': '2026-10-25T01:00:00Z',
                          'title': title, 'text': text}],
            'result': {'summary': '**示例摘要**', 'completed': [], 'progress': [], 'unfinished': [],
                       'priorities': [{'text': '**先验证**\n\n- 检查输出', 'refs': ['E1']}]}}


def rendered(tmp_path, record):
    config = initialize(tmp_path / 'data')
    write_briefing(config, record)
    path = config.root / 'briefings/2026-10-26'
    return path.with_suffix('.html').read_text(), path.with_suffix('.md').read_text()


def test_project_labels_use_current_task_project_in_every_section(tmp_path):
    record = report()
    record['evidence'][0]['project'] = 'original-project'
    record['result']['tasks'] = [{'id': 'T1', 'projects': ['new-project', 'shared-project']}]
    item = {**record['result']['priorities'][0], 'task_id': 'T1'}
    for key in ('priorities', 'completed', 'progress', 'unfinished'):
        record['result'][key] = [item]
    html, md = rendered(tmp_path, record)
    assert html.count('<span class="project-tag">new-project</span>') == 4
    assert html.count('<span class="project-tag">shared-project</span>') == 4
    assert md.count('**new-project · shared-project**') == 4
    assert '来源项目：original-project' not in html


def test_old_reports_use_source_project_and_unknown_projects_are_explicit(tmp_path):
    record = report()
    record['evidence'][0]['project'] = 'original-project'
    html, _ = rendered(tmp_path, record)
    assert '<span class="project-tag">来源项目：original-project</span>' in html
    record['result']['tasks'] = [{'id': 'T1', 'projects': []}]
    record['result']['priorities'][0]['task_id'] = 'T1'
    html, _ = rendered(tmp_path, record)
    assert '<span class="project-tag">未归属项目</span>' in html


def test_project_labels_are_literal_in_html_and_markdown(tmp_path):
    record = report()
    project = '<img src=x> **bold** [link](https://example.invalid)'
    record['result']['tasks'] = [{'id': 'T1', 'projects': [project]}]
    record['result']['priorities'][0]['task_id'] = 'T1'
    html, md = rendered(tmp_path, record)
    for document in (Document(html), Document(render_markdown(md, 'export'))):
        assert project in ''.join(document.text)
        assert not any(tag == 'img' or (tag == 'a' and attrs.get('href') == 'https://example.invalid')
                       for tag, attrs in document.tags)


def test_browser_entities_are_decoded_and_duplicate_title_is_not_rendered(tmp_path):
    value = '示例 &quot;标题&quot; &amp; 说明'
    html, md = rendered(tmp_path, report(source='browser_history', title=value, text=value))
    visible = '\n'.join(Document(html).text)
    assert '示例 "标题" & 说明' in visible
    assert '&quot;' not in visible and '&amp;' not in visible
    assert visible.count('示例 "标题" & 说明') == 1
    assert md.count('示例 "标题" & 说明') == 1


def test_markdown_is_rendered_in_summary_items_and_evidence(tmp_path):
    html, _ = rendered(tmp_path, report(text='## 示例标题\n\n**粗体**与*斜体*、`inline`\n\n- 第一项\n- 第二项\n\n> 引用'))
    document = Document(html)
    tags = [tag for tag, _ in document.tags]
    assert tags.count('strong') >= 3  # summary, recommendation, source body
    assert 'em' in tags and 'code' in tags and 'blockquote' in tags
    assert '**粗体**' not in '\n'.join(document.text)


def test_single_block_summary_becomes_one_bullet_per_point(tmp_path):
    record = report(text='synthetic')
    record['evidence'][0]['project'] = 'novel2026'
    record['result']['summary'] = '昨日集中两条线。novel2026：完成细则并提交。Codex 侧仅咨询工具。'
    html, md = rendered(tmp_path, record)
    assert '<ul class="summary-list">' in html
    assert re.findall(r'<li>(.*?)</li>', html)[:3] == [
        '昨日集中两条线。',
        '<span class="summary-project">novel2026</span>：完成细则并提交。',
        'Codex 侧仅咨询工具。']
    assert '- 昨日集中两条线。\n- **novel2026**：完成细则并提交。\n- Codex 侧仅咨询工具。' in md


def test_summary_without_several_points_stays_prose_and_keeps_markdown(tmp_path):
    record = report(text='synthetic')
    record['result']['summary'] = '只有一句话。'
    html, _ = rendered(tmp_path, record)
    assert 'class="summary-list"' not in html and '<p>只有一句话。</p>' in html
    record['result']['summary'] = '**一句话。**'
    html, _ = rendered(tmp_path, record)
    assert 'class="summary-list"' not in html and '<strong>一句话。</strong>' in html


def test_code_fences_are_preserved_in_export_and_rendered_as_code(tmp_path):
    text = '```python\nprint("&quot; **literal**")\n```'
    html, md = rendered(tmp_path, report(text=text))
    assert text in md
    assert '<pre><code' in html
    assert any(tag == 'code' and attrs.get('class') == 'language-python' for tag, attrs in Document(html).tags)
    assert '&quot; **literal**' in '\n'.join(Document(html).text)


def test_indented_code_keeps_its_leading_spaces_and_literal_markers(tmp_path):
    html, md = rendered(tmp_path, report(text='    **literal code**\n    second line'))
    assert '<pre><code>**literal code**\nsecond line' in html
    assert '<strong>literal code</strong>' not in render_markdown(md, 'export')


def test_tables_nested_lists_tasks_strikethrough_and_links(tmp_path):
    text = '''| 名称 | 状态 |
| --- | --- |
| 示例 | **通过** |

1. 外层
   - 内层

- [x] 已检查
- [ ] 待处理

~~旧方案~~ [文档](https://example.invalid/guide)
'''
    html, md = rendered(tmp_path, report(text=text))
    document = Document(html)
    assert all(tag in [name for name, _ in document.tags] for tag in ('table', 'thead', 'tbody', 'ol', 'del'))
    inputs = [attrs for name, attrs in document.tags if name == 'input']
    assert len(inputs) == 2 and all('disabled' in attrs for attrs in inputs)
    assert any(attrs.get('href') == 'https://example.invalid/guide' for name, attrs in document.tags if name == 'a')
    assert '- [x] 已检查' in md


@pytest.mark.parametrize('text', [
    '<script>alert(1)</script>',
    '<img src=x onerror="alert(1)">',
    '[危险](javascript:alert%281%29)',
    '[危险](java&#x73;cript:alert%281%29)',
    '[危险](data:text/html,payload)',
    '[本地](file:///private/example)',
    '![跟踪像素](https://example.invalid/pixel.png)',
    '[损坏网址](http://[broken)',
])
def test_markdown_cannot_execute_html_or_load_remote_resources(tmp_path, text):
    html, _ = rendered(tmp_path, report(text=text))
    document = Document(html)
    assert not any(tag in {'script', 'img', 'iframe', 'object'} for tag, attrs in document.tags)
    links = [attrs.get('href', '') for tag, attrs in document.tags if tag == 'a']
    assert all(href.startswith(('#', 'https://', 'http://')) for href in links)


def test_footnotes_are_scoped_to_each_excerpt(tmp_path):
    record = report(text='正文[^1]\n\n[^1]: 第一份注释')
    record['evidence'].append({**record['evidence'][0], 'id': 'E2', 'text': '正文[^1]\n\n[^1]: 第二份注释'})
    html, md = rendered(tmp_path, record)
    document = Document(html)
    identifiers = [attrs['id'] for _, attrs in document.tags if 'id' in attrs]
    assert len(identifiers) == len(set(identifiers))
    assert 'E1-fn-1' in identifiers and 'E2-fn-1' in identifiers
    exported = render_markdown(md, 'export')
    assert '第一份注释' in exported and '第二份注释' in exported


def test_duplicate_message_title_keeps_markdown_and_local_time(tmp_path):
    html, _ = rendered(tmp_path, report(title='**示例标题**', text='**示例标题**'))
    document = Document(html)
    assert '<strong>示例标题</strong>' in html
    assert '\n'.join(document.text).count('示例标题') == 1
    assert '2026-10-25 09:00' in html and ' ·  · ' not in html


def test_multiline_recommendation_preserves_its_code_fence_in_markdown(tmp_path):
    record = report(text='示例')
    record['result']['priorities'][0]['text'] = '检查结果：\n\n```text\nline one\nline two\n```'
    _, md = rendered(tmp_path, record)
    assert '  ```text\n  line one\n  line two\n  ```\n\n  [E1]' in md


def test_truncated_fence_does_not_swallow_next_excerpt_in_markdown(tmp_path):
    record = report(text='```python\nprint("partial")')
    record['evidence'][0]['excerpt_truncated'] = True
    record['evidence'].append({**record['evidence'][0], 'id': 'E2', 'text': '**下一份摘录**'})
    _, md = rendered(tmp_path, record)
    exported = render_markdown(md, 'export')
    assert '<h3>E2</h3>' in exported
    assert '<strong>下一份摘录</strong>' in exported


def test_link_references_do_not_resolve_to_another_excerpt(tmp_path):
    record = report(text='[说明][doc]\n\n[doc]: https://example.invalid/one')
    record['evidence'].append({**record['evidence'][0], 'id': 'E2',
                              'text': '[说明][doc]\n\n[doc]: https://example.invalid/two'})
    _, md = rendered(tmp_path, record)
    exported = render_markdown(md, 'export')
    assert 'href="https://example.invalid/one"' in exported
    assert 'href="https://example.invalid/two"' in exported


def test_items_split_into_headline_and_details_without_rewording(tmp_path):
    record = report(text='synthetic')
    record['result']['completed'] = [
        {'text': '规范落地并推送：第三章改写，已提交。', 'refs': ['E1']},
        {'text': '细纲 v3 完成。边界：正文未写。', 'refs': ['E1']},
        {'text': '只有一句。', 'refs': ['E1']},
        {'text': '**含标记**的条目保持 Markdown。', 'refs': ['E1']}]
    html, md = rendered(tmp_path, record)
    assert '<p class="lead">规范落地并推送</p><p class="detail">第三章改写，已提交。</p>' in html
    assert '<p class="lead">细纲 v3 完成。</p><p class="detail">边界：正文未写。</p>' in html
    assert '<p class="lead">只有一句。</p><div class="references">' in html
    assert '<strong>含标记</strong>' in html
    assert '规范落地并推送：第三章改写，已提交。' in md  # Export keeps the model's wording.


def test_sections_lead_with_actions_and_group_entries_by_project(tmp_path):
    record = report(text='synthetic')
    record['result']['tasks'] = [{'id': 'A', 'projects': ['alpha']}, {'id': 'B', 'projects': ['beta']}]
    record['result']['completed'] = [{'text': f'第{n}项。', 'refs': ['E1'], 'task_id': task}
                                     for n, task in enumerate('ABA', start=1)]
    record['result']['unfinished'] = [{'text': '待确认。', 'refs': ['E1']}]
    html, md = rendered(tmp_path, record)
    positions = [html.index(f'id="{key}"') for key in ('priorities', 'unfinished', 'progress', 'completed')]
    assert positions == sorted(positions)
    assert html.index('class="focus checkin is-empty"') < positions[1]
    assert [md.index('## ' + label) for label in ('今日建议', '主动跟进', '未完成', '进行中', '昨日成果')] == \
        sorted(md.index('## ' + label) for label in ('今日建议', '主动跟进', '未完成', '进行中', '昨日成果'))
    completed = html[positions[3]:]
    assert completed.count('<span class="project-tag">alpha</span>') == 1
    assert completed.index('第1项') < completed.index('第3项') < completed.index('第2项')
    assert '<a class="tone-completed" href="#completed">已完成<b>3</b></a>' in html
    assert '<a class="tone-progress is-empty" href="#progress">进行中<b>0</b></a>' in html


def test_incomplete_input_is_flagged_next_to_the_summary(tmp_path):
    record = report(text='synthetic')
    html, _ = rendered(tmp_path, record)
    assert '<p class="caveat">' in html
    record['source_health'] = {'git': 'error'}
    html, _ = rendered(tmp_path, record)
    caveat = html.index('<p class="caveat warn">')
    assert caveat < html.index('id="priorities"') and '来源采集未全部成功：git' in html[caveat:]
