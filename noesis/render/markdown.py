"""Markdown presentation with literal code and no automatic remote resource loads."""

from html import escape
from textwrap import indent
from urllib.parse import urlsplit

from .._vendor.mistune import HTMLRenderer, create_markdown
from .._vendor.mistune.renderers.markdown import MarkdownRenderer
from .._vendor.mistune.util import safe_entity


class BriefingRenderer(HTMLRenderer):
    def text(self, text):
        # Decode character references in prose, while code remains literal.
        return safe_entity(text)

    def link(self, text, url, title=None):
        try:
            parsed = urlsplit(url)
        except ValueError:
            return text
        if url.startswith('#') or (parsed.scheme.lower() in {'http', 'https'} and parsed.netloc):
            return super().link(text, url, title)
        return text

    def image(self, text, url, title=None):
        # Keep the caption/link without loading tracking pixels or private images.
        return '<span class="image-reference">图片：' + self.link(text or '查看图片', url, title) + '</span>'


PLUGINS = ['strikethrough', 'table', 'task_lists', 'url', 'footnotes']
_markdown = create_markdown(renderer=BriefingRenderer(escape=True), plugins=PLUGINS)


def render_markdown(text, namespace):
    html = _markdown(text)
    # Each source is parsed separately; scope footnotes to their source so clicks
    # cannot jump to a different excerpt's identically numbered footnote.
    for prefix in ('fn-', 'fnref-'):
        html = html.replace(f'id="{prefix}', f'id="{namespace}-{prefix}')
        html = html.replace(f'href="#{prefix}', f'href="#{namespace}-{prefix}')
    return html


class ExportRenderer(MarkdownRenderer):
    """Keep each excerpt self-contained when concatenated into one Markdown file."""

    def __init__(self, namespace):
        super().__init__()
        self.namespace = namespace

    def link(self, token, state):
        # Resolve source-local reference links before combining independent texts.
        return super().link({**token, 'label': None}, state)

    def render_referrences(self, state):
        return []  # All reference links are emitted inline above.

    def strikethrough(self, token, state):
        return '~~' + self.render_children(token, state) + '~~'

    def footnote_ref(self, token, state):
        return f'[^{self.namespace}-{token["attrs"]["index"]}]'

    def footnote_item(self, token, state):
        text = self.render_children(token, state).strip('\n')
        return self.footnote_ref(token, state) + ': ' + indent(text, '    ').lstrip() + '\n\n'

    def footnotes(self, token, state):
        return '\n' + self.render_children(token, state)

    def inline_html(self, token, state):
        return escape(token['raw'], quote=False)

    def block_html(self, token, state):
        return self.inline_html(token, state) + '\n\n'


def export_markdown(text, namespace):
    # The upstream renderer closes truncated code fences without changing code.
    return create_markdown(renderer=ExportRenderer(namespace), plugins=PLUGINS)(text).rstrip('\n')
