import copy
import difflib
import pathlib
import re
import sys
import unittest

from docutils import core, nodes

from rst2md import convert_doctree_to_md, parse_rst

TESTS = pathlib.Path(__file__).parent
DATA = TESTS / 'data'

# git submodule: rst2txt, the plain text writer by the same author
sys.path.insert(0, str(TESTS / 'rst2txt'))
from rst2txt import writer as txt  # noqa: E402

FIXTURES = [
    DATA / 'cpython' / 'Doc' / 'whatsnew' / '3.15.rst',
    DATA / 'linux' / 'Documentation' / 'kernel-hacking' / 'hacking.rst',
]


class TextTranslator(txt.TextTranslator):
    # rst2md's Sphinx stubs, unknown to rst2txt
    visit_seealso = txt.TextTranslator._visit_admonition
    depart_seealso = txt.TextTranslator._make_depart_admonition('see also')

    def visit_ref(self, node: nodes.Element) -> None:
        self.add_text(node.astext() or node['label'])
        raise nodes.SkipNode


class Writer(txt.Writer):
    def __init__(self) -> None:
        super().__init__()
        self.translator_class = TextTranslator


def _to_txt(document: nodes.document) -> str:
    return core.publish_from_doctree(
        document,
        writer=Writer(),
        settings_overrides={'output_encoding': 'unicode'},
    )


def _txt_words(document: nodes.document) -> list[str]:
    return _words(_to_txt(copy.deepcopy(document)))


def _md_words(document: nodes.document) -> list[str]:
    md = convert_doctree_to_md(copy.deepcopy(document))
    # Markdown only: fence info strings
    md = re.sub(r'(?m)^(\s*```)\S+', r'\1', md)
    # rst2txt drops images and link targets
    md = re.sub(r'!\[[^\]]*\]\([^)\s]*\)', '', md)
    md = re.sub(r'\]\([^)\s]*\)', ']', md)
    return _words(md)


def _words(text: str) -> list[str]:
    return re.findall(r'[^\W_]+', text.lower())


def _pop_tables(document: nodes.document) -> list[nodes.document]:
    # rst2txt grids interleave the lines of a row's cells: word order only
    # holds outside tables, so each table moves to a document of its own
    tables = []
    for table in list(document.findall(nodes.table)):
        table.parent.remove(table)
        tables.append(document.copy())
        tables[-1].append(table)
    return tables


def _diff(a: list[str], b: list[str]) -> list[str]:
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [
        f'{op}: {" ".join(a[i1:i2])!r} -> {" ".join(b[j1:j2])!r}'
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
        if op != 'equal'
    ]


class TestTextEquivalence(unittest.TestCase):
    maxDiff = None

    def test_same_words(self):
        for path in FIXTURES:
            document = parse_rst(str(path), path.read_text())
            tables = _pop_tables(document)
            with self.subTest(path=path.name):
                self.assertEqual(
                    [], _diff(_txt_words(document), _md_words(document))
                )
            for i, table in enumerate(tables):
                with self.subTest(path=path.name, table=i):
                    self.assertEqual(
                        set(_txt_words(table)), set(_md_words(table))
                    )


if __name__ == '__main__':
    unittest.main()
