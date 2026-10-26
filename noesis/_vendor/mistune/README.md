# Mistune 3.3.4

Source: https://github.com/lepture/mistune/tree/v3.3.4

Distribution: `mistune-3.3.4-py3-none-any.whl` from PyPI.
SHA-256: `ee015381e955e370962968befe1d729ab60fafb6a715ac6751763fbce38c8d4a`

BSD-3-Clause license: LICENSE.

Included: parser core, HTML/Markdown renderers, and formatting/footnotes/table/task-list/URL plugins.
Unused directives, renderers and plugins are omitted. Python source is unchanged except
the plugin registry's `mistune.plugins.*` namespace becomes `noesis._vendor.mistune.plugins.*`.
Keep upstream parser behavior in this directory; application-specific rendering lives in
`noesis/render/markdown.py`. No runtime downloads or separately installed packages are needed.
