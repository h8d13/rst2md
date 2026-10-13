# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
A utility and library to convert a reStructuredText document to Markdown.
"""

__version__ = '0.2'

import collections
import dataclasses
import re
import typing as ty

from docutils import core, nodes, utils
from docutils.parsers.rst import directives, roles
from docutils.parsers.rst.directives import admonitions, body


class UnsupportedNode(Exception):
    def __init__(self, node: nodes.Node):
        message = f'unsupported node type {type(node)!r}, data={node}'
        super().__init__(message)


@dataclasses.dataclass
class Context:
    document: nodes.document
    # section -> Markdown heading anchor, used to resolve internal links
    anchors: dict[nodes.Element, str]


# Sphinx stubs
#
# Sphinx roles and directives are not part of docutils. Register just enough
# of them that Sphinx documents parse, rendering each as Sphinx displays it.


class seealso(nodes.Admonition, nodes.Element):
    pass


class ref(nodes.Inline, nodes.TextElement):
    # resolved at conversion time: the label may point to a section that is
    # parsed after the reference
    pass


class SeeAlso(admonitions.BaseAdmonition):
    node_class = seealso


class DocTest(body.CodeBlock):
    def run(self):
        # the argument is a doctest group name, the content a console session
        self.arguments = ['pycon']
        return super().run()


_EXPLICIT_TITLE = re.compile(r'^(.+?)\s*<([^<]+)>$', re.DOTALL)

_PAREN_ROLES = {'func', 'meth', 'py:func', 'py:meth', 'c:func'}

_OBJECT_ROLES = {
    'attr',
    'class',
    'const',
    'data',
    'deco',
    'exc',
    'func',
    'meth',
    'mod',
    'obj',
    'type',
    'c:data',
    'c:func',
    'c:macro',
    'c:member',
    'c:struct',
    'c:type',
    'c:var',
}
_OBJECT_ROLES |= {f'py:{name}' for name in _OBJECT_ROLES if ':' not in name}

_LITERAL_ROLES = {'c:expr', 'file', 'kbd', 'samp'}

# cross-references, which accept `title <target>`
_LITERAL_XREF_ROLES = {'envvar', 'keyword', 'monitoring-event', 'option'}


def _split_target(text: str) -> tuple[str, str, bool]:
    """Split Sphinx cross-reference text into (title, target, explicit)."""
    text = ' '.join(text.split())  # may wrap over several lines
    match = _EXPLICIT_TITLE.match(text)
    if match:
        return match.group(1), match.group(2), True
    target = text.lstrip('!')
    if target.startswith('~'):  # display the last component only
        target = target[1:]
        return target.rpartition('.')[2], target, False
    return target, target, False


def _object_node(name: str, rawtext: str, text: str) -> nodes.Node:
    title, _, explicit = _split_target(text)
    if not explicit:  # a leading dot is a search hint, not displayed
        title = title.lstrip('.')
    if name in _PAREN_ROLES and not explicit and not title.endswith(')'):
        title += '()'
    elif name.endswith('deco') and not explicit:
        title = '@' + title
    return nodes.literal(rawtext, title)


def _ref_node(name: str, rawtext: str, text: str) -> nodes.Node:
    title, target, explicit = _split_target(text)
    return ref(rawtext, title if explicit else '', label=target)


def _gh_node(name: str, rawtext: str, text: str) -> nodes.Node:
    uri = f'https://github.com/python/cpython/issues/{text}'
    return nodes.reference(rawtext, f'gh-{text}', refuri=uri)


def _cve_node(name: str, rawtext: str, text: str) -> nodes.Node:
    uri = f'https://www.cve.org/CVERecord?id=CVE-{text}'
    return nodes.reference(rawtext, f'CVE-{text}', refuri=uri)


def _pep_node(name: str, rawtext: str, text: str) -> nodes.Node:
    # unlike docutils, Sphinx allows an explicit title and an #anchor
    title, target, explicit = _split_target(text)
    number, _, anchor = target.partition('#')
    prefix, url = {
        'pep': ('PEP', f'https://peps.python.org/pep-{int(number):04d}/'),
        'rfc': ('RFC', f'https://datatracker.ietf.org/doc/html/rfc{number}'),
    }[name]
    title = title if explicit else f'{prefix} {number}'
    uri = f'{url}#{anchor}' if anchor else url
    return nodes.reference(rawtext, title, refuri=uri)


def _pypi_node(name: str, rawtext: str, text: str) -> nodes.Node:
    uri = f'https://pypi.org/project/{text}/'
    return nodes.reference(rawtext, text, refuri=uri)


def _make_role(make_node: ty.Callable[[str, str, str], nodes.Node]):
    def role(name, rawtext, text, lineno, inliner, options=None, content=None):
        return [make_node(name, rawtext, utils.unescape(text))], []

    return role


def _register_sphinx_stubs() -> None:
    simple = {
        'term': lambda n, raw, text: nodes.Text(_split_target(text)[0]),
        'ref': _ref_node,
        'program': lambda n, raw, text: nodes.strong(raw, text),
        'manpage': lambda n, raw, text: nodes.emphasis(
            raw, _split_target(text)[0]
        ),
        'gh': _gh_node,
        'cve': _cve_node,
        'pep': _pep_node,
        'rfc': _pep_node,
        'pypi': _pypi_node,
    }
    simple |= dict.fromkeys(_OBJECT_ROLES, _object_node)
    simple |= dict.fromkeys(
        _LITERAL_ROLES, lambda n, raw, text: nodes.literal(raw, text)
    )
    simple |= dict.fromkeys(
        _LITERAL_XREF_ROLES,
        lambda n, raw, text: nodes.literal(raw, _split_target(text)[0]),
    )
    for name, make_node in simple.items():
        roles.register_local_role(name, _make_role(make_node))

    directives.register_directive('seealso', SeeAlso)
    directives.register_directive('doctest', DocTest)


# Markdown helpers


class Markdown(str):
    # already rendered, passed through block conversion as is
    pass


def _escape(text: str) -> str:
    text = re.sub(r'([\\`*<\[\]])', r'\\\1', text)
    # intraword underscores are literal in CommonMark, a run touching a word
    # boundary may open or close emphasis: escape all of it
    return re.sub(
        r'(?<!\w)_+|_+(?!\w)', lambda m: r'\_' * len(m.group()), text
    )


def _code_span(text: str) -> str:
    longest = max(map(len, re.findall('`+', text)), default=0)
    fence = '`' * (longest + 1)
    if text.startswith('`') or text.endswith('`'):
        text = f' {text} '
    return f'{fence}{text}{fence}'


def _link(text: str, uri: str) -> str:
    if re.search(r'[\s()<>]', uri):
        uri = f'<{uri}>'
    return f'[{text}]({uri})'


def _indent(text: str, first: str, rest: str) -> str:
    lines = text.split('\n')
    out = [first + lines[0]]
    out += [rest + line if line else rest.rstrip() for line in lines[1:]]
    return '\n'.join(out)


def _join_items(items: ty.Iterable[str]) -> str:
    # items holding several blocks make a loose list: space all of them
    items = list(items)
    loose = any('\n\n' in item for item in items)
    return ('\n\n' if loose else '\n').join(items)


def _labelled(label: str, text: str) -> str:
    # list item led by a label; blocks such as code fences must start a line
    if label and '\n' in text:
        text = f'{label}\n\n{text}'
    elif label:
        text = f'{label} {text}'
    return _indent(text, '- ', '  ')


def _slug(text: str) -> str:
    # GitHub's heading anchor algorithm
    text = re.sub(r'[^\w\- ]', '', text.strip().lower())
    return text.replace(' ', '-')


def _find_target(
    document: nodes.document, node: nodes.Element
) -> nodes.Element | None:
    # internal link to its target node, None if not in this document
    if isinstance(node, ref):
        name = nodes.fully_normalize_name(node['label'])
        node_id = document.nameids.get(name)
    else:
        node_id = node.get('refid')
    return document.ids.get(node_id) if node_id else None


def _section_anchors(document: nodes.document) -> dict[nodes.Element, str]:
    anchors: dict[nodes.Element, str] = {}
    seen: collections.Counter[str] = collections.Counter()
    for section in document.findall(nodes.section):
        slug = _slug(section[0].astext())
        anchors[section] = f'{slug}-{seen[slug]}' if seen[slug] else slug
        seen[slug] += 1
    return anchors


# Inline nodes


def _convert_inlines(ctx: Context, parent: nodes.Element) -> str:
    return ''.join(_convert_inline(ctx, node) for node in parent.children)


def _convert_inline(ctx: Context, node: nodes.Node) -> str:
    for cls in type(node).__mro__:
        if cls in _INLINE:
            return _INLINE[cls](ctx, node)
    raise UnsupportedNode(node)


def _convert_text(ctx: Context, text: nodes.Text) -> str:
    return _escape(text.astext().replace('\n', ' '))


def _convert_literal(ctx: Context, literal: nodes.literal) -> str:
    return _code_span(literal.astext().replace('\n', ' '))


def _convert_emphasis(ctx: Context, emphasis: nodes.emphasis) -> str:
    return f'*{_convert_inlines(ctx, emphasis)}*'


def _convert_strong(ctx: Context, strong: nodes.strong) -> str:
    return f'**{_convert_inlines(ctx, strong)}**'


def _convert_image(ctx: Context, image: nodes.image) -> str:
    alt = image.get('alt') or 'image'
    return f'![{_escape(alt)}]({image["uri"]})'


def _convert_reference(ctx: Context, reference: nodes.reference) -> str:
    text = _convert_inlines(ctx, reference)
    if 'refuri' in reference:
        uri = reference['refuri']
        if reference.astext() == uri:  # plain URL
            return f'<{uri}>'
        return _link(text, uri)
    target = _find_target(ctx.document, reference)
    if target is None:
        raise UnsupportedNode(reference)
    if target not in ctx.anchors:  # only headings have Markdown anchors
        return text
    return _link(text, '#' + ctx.anchors[target])


def _convert_ref(ctx: Context, node: ref) -> str:
    target = _find_target(ctx.document, node)
    title = node.astext()
    if target not in ctx.anchors:
        # not a heading, or in another document: keep the text, drop the link
        return _escape(title or node['label'])
    title = title or target[0].astext()
    return _link(_escape(title), '#' + ctx.anchors[target])


def _convert_title_reference(
    ctx: Context, title_reference: nodes.title_reference
) -> str:
    return f'*{_convert_inlines(ctx, title_reference)}*'


def _convert_target(ctx: Context, target: nodes.target) -> str:
    # inline targets only define link names, already resolved by docutils
    return _convert_inlines(ctx, target)


_INLINE: dict[type, ty.Callable[[Context, ty.Any], str]] = {
    nodes.Text: _convert_text,
    nodes.literal: _convert_literal,
    nodes.emphasis: _convert_emphasis,
    nodes.strong: _convert_strong,
    nodes.image: _convert_image,
    nodes.reference: _convert_reference,
    nodes.title_reference: _convert_title_reference,
    nodes.target: _convert_target,
    ref: _convert_ref,
}


# Block nodes

_E = ty.TypeVar('_E', bound=nodes.Element)


def _children(node: nodes.Element, cls: type[_E]) -> list[_E]:
    # docutils types children as plain nodes
    return [child for child in node.children if isinstance(child, cls)]


def _convert_blocks(
    ctx: Context, children: ty.Iterable[ty.Union[nodes.Node, 'Markdown']]
) -> str:
    blocks = (_convert_block(ctx, node) for node in children)
    return '\n\n'.join(block for block in blocks if block)


def _convert_block(
    ctx: Context, node: ty.Union[nodes.Node, 'Markdown']
) -> str:
    if isinstance(node, Markdown):
        return node
    for cls in type(node).__mro__:
        if cls in _BLOCK:
            return _BLOCK[cls](ctx, node)
    raise UnsupportedNode(node)


def _convert_skip(ctx: Context, node: nodes.Node) -> str:
    # targets and substitutions are resolved by docutils, comments are
    # dropped, and system messages left are below halt_level (info)
    return ''


def _convert_section(ctx: Context, section: nodes.section) -> str:
    level = 0
    node: nodes.Node | None = section
    while node is not None:
        level += isinstance(node, nodes.section)
        node = node.parent
    title = _convert_inlines(ctx, _children(section, nodes.title)[0])
    heading = Markdown('#' * min(level, 6) + ' ' + title)
    return _convert_blocks(ctx, [heading, *section[1:]])


def _convert_paragraph(ctx: Context, paragraph: nodes.paragraph) -> str:
    return _convert_inlines(ctx, paragraph)


def _convert_rubric(ctx: Context, rubric: nodes.rubric) -> str:
    return f'**{_convert_inlines(ctx, rubric)}**'


def _convert_list_item(
    ctx: Context, list_item: nodes.list_item, marker: str
) -> str:
    text = _convert_blocks(ctx, list_item.children)
    return _indent(text, marker, ' ' * len(marker))


def _convert_bullet_list(ctx: Context, bullet_list: nodes.bullet_list) -> str:
    items = (
        _convert_list_item(ctx, item, '- ')
        for item in _children(bullet_list, nodes.list_item)
    )
    return _join_items(items)


def _convert_enumerated_list(
    ctx: Context, enumerated_list: nodes.enumerated_list
) -> str:
    start = enumerated_list.get('start', 1)
    items = (
        _convert_list_item(ctx, item, f'{number}. ')
        for number, item in enumerate(
            _children(enumerated_list, nodes.list_item), start
        )
    )
    return _join_items(items)


def _convert_field_list(ctx: Context, field_list: nodes.field_list) -> str:
    fields = []
    for field in _children(field_list, nodes.field):
        name = _children(field, nodes.field_name)[0]
        label = f'**{_convert_inlines(ctx, name)}:**'
        text = _convert_blocks(ctx, field[-1].children)
        fields.append(_labelled(label, text))
    return _join_items(fields)


def _convert_definition_list(
    ctx: Context, definition_list: nodes.definition_list
) -> str:
    # no definition lists in GFM: a list of terms, definitions nested below
    items = []
    for item in _children(definition_list, nodes.definition_list_item):
        term = f'**{_convert_inlines(ctx, _children(item, nodes.term)[0])}**'
        for classifier in _children(item, nodes.classifier):
            term += f' *{_convert_inlines(ctx, classifier)}*'
        definition = _children(item, nodes.definition)[0]
        text = _convert_blocks(ctx, definition.children)
        items.append(_indent(f'{term}\n\n{text}', '- ', '  '))
    return _join_items(items)


def _convert_literal_block(
    ctx: Context, literal_block: nodes.literal_block
) -> str:
    text = literal_block.astext()
    # like Sphinx, detect interactive sessions in unlabelled blocks
    default = 'pycon' if text.startswith('>>> ') else ''
    language = next(
        (cls for cls in literal_block['classes'] if cls != 'code'), default
    )
    longest = max(map(len, re.findall('^`+', text, re.MULTILINE)), default=0)
    fence = '`' * max(longest + 1, 3)
    return f'{fence}{language}\n{text}\n{fence}'


def _convert_block_quote(ctx: Context, block_quote: nodes.block_quote) -> str:
    text = _convert_blocks(ctx, block_quote.children)
    # an indented target alone parses as a quote, rendering nothing
    return _indent(text, '> ', '> ') if text else ''


def _convert_attribution(ctx: Context, attribution: nodes.attribution) -> str:
    return f'— {_convert_inlines(ctx, attribution)}'


def _convert_admonition(ctx: Context, admonition: nodes.Element) -> str:
    children = admonition.children
    if isinstance(admonition, nodes.admonition):  # title is a child
        title = _convert_inlines(ctx, _children(admonition, nodes.title)[0])
        children = children[1:]
    elif isinstance(admonition, seealso):
        title = 'See also'
    else:
        title = admonition.tagname.capitalize()
    text = _convert_blocks(ctx, [Markdown(f'**{title}**'), *children])
    return _indent(text, '> ', '> ')


def _convert_table(ctx: Context, table: nodes.table) -> str:
    rows = [
        [_convert_blocks(ctx, entry.children) for entry in row]
        for row in table.findall(nodes.row)
    ]
    header = rows.pop(0) if table.next_node(nodes.thead) else None
    if any('\n' in cell for row in rows for cell in row):
        text = _convert_table_as_list(header, rows)
    else:
        text = _convert_table_as_pipes(header, rows)
    title = table.next_node(nodes.title)
    if title is None:
        return text
    return f'**{_convert_inlines(ctx, title)}**\n\n{text}'


def _convert_table_as_pipes(
    header: list[str] | None, rows: list[list[str]]
) -> str:
    def line(cells: list[str]) -> str:
        return '| ' + ' | '.join(c.replace('|', r'\|') for c in cells) + ' |'

    width = len(rows[0]) if rows else len(header or [])
    lines = [line(header or [''] * width), line(['---'] * width)]
    lines += [line(row) for row in rows]
    return '\n'.join(lines)


def _convert_table_as_list(
    header: list[str] | None, rows: list[list[str]]
) -> str:
    # pipe tables cannot hold multi-line cells: one list per row instead
    items = []
    for row in rows:
        labels = header or [''] * len(row)
        cells = [
            _labelled(f'**{label}:**' if label else '', cell)
            for label, cell in zip(labels, row)
        ]
        items.append('\n'.join(cells))
    return '\n\n'.join(items)


def _convert_transition(ctx: Context, transition: nodes.transition) -> str:
    return '---'


_BLOCK: dict[type, ty.Callable[[Context, ty.Any], str]] = {
    nodes.section: _convert_section,
    nodes.paragraph: _convert_paragraph,
    nodes.rubric: _convert_rubric,
    nodes.bullet_list: _convert_bullet_list,
    nodes.enumerated_list: _convert_enumerated_list,
    nodes.field_list: _convert_field_list,
    nodes.definition_list: _convert_definition_list,
    nodes.literal_block: _convert_literal_block,
    nodes.block_quote: _convert_block_quote,
    nodes.attribution: _convert_attribution,
    nodes.Admonition: _convert_admonition,
    nodes.table: _convert_table,
    nodes.image: _convert_image,
    nodes.transition: _convert_transition,
    nodes.target: _convert_skip,
    nodes.comment: _convert_skip,
    nodes.system_message: _convert_skip,
    nodes.substitution_definition: _convert_skip,
}


def parse_rst(name: str, data: str) -> nodes.document:
    """Parse a reStructuredText document, with the Sphinx stubs registered.

    :param name: The path of the source document, used to resolve includes.
    :param data: The contents of the source document.
    :returns: The document tree.
    :raises docutils.utils.SystemMessage: docutils reported a warning or
        worse, e.g. an unknown role.
    """
    _register_sphinx_stubs()
    return core.publish_doctree(
        data,
        source_path=name,
        settings_overrides={
            # leave syntax highlighting to the Markdown renderer
            'syntax_highlight': 'none',
            # keep the document title as a heading
            'doctitle_xform': False,
            'halt_level': 2,
        },
    )


def convert_doctree_to_md(document: nodes.document) -> str:
    """Convert a parsed document to Markdown.

    :param document: The document tree, as returned by :func:`parse_rst`.
    :returns: The converted document.
    :raises UnsupportedNode: The document holds a node with no Markdown
        conversion.
    """
    ctx = Context(document, _section_anchors(document))
    return _convert_blocks(ctx, document.children).strip()


def convert_rst_to_md(name: str, data: str) -> str:
    """Convert a reStructuredText document to Markdown.

    Sphinx roles and directives used by the CPython documentation are
    rendered as Sphinx displays them. Cross-references link only to
    headings of this document, others keep their text.

    :param name: The path of the source document, used to resolve includes.
    :param data: The contents of the source document.
    :returns: The converted document.
    :raises UnsupportedNode: The document holds a node with no Markdown
        conversion.
    :raises docutils.utils.SystemMessage: docutils reported a warning or
        worse, e.g. an unknown role.
    """
    return convert_doctree_to_md(parse_rst(name, data))


if __name__ == '__main__':
    import argparse
    import pathlib

    parser = argparse.ArgumentParser(
        prog='python -m rst2md',
        description='A utility to convert rST to Markdown',
    )
    parser.add_argument(
        'path',
        type=pathlib.Path,
        help='Path to reStructuredText file to convert',
    )
    args = parser.parse_args()
    print(convert_rst_to_md(str(args.path), args.path.read_text()))
