import pathlib
import re
import unittest

from rst2md import convert_rst_to_md

DATA = pathlib.Path(__file__).parent / 'data'

# leftovers of rST syntax that should never survive into Markdown
RST_LEFTOVERS = [
    re.compile(r':[\w:-]+:`'),  # interpreted text roles
    re.compile(r'^\s*\.\. ', re.MULTILINE),  # directives, comments, targets
    re.compile(r'``'),  # rST inline literals
    re.compile(r'`_'),  # rST references
]


def _strip_code(md: str) -> str:
    # fences may be indented in lists, but must open their line: a fence
    # after other text stays in prose and is caught as a leftover
    prose, fenced = [], False
    for line in md.split('\n'):
        if re.match(r'\s*```', line):
            fenced = not fenced
        elif not fenced:
            prose.append(line)
    return re.sub(r'(`+)[^`].*?\1', '', '\n'.join(prose))


class FixtureMixin:
    path: pathlib.Path
    md: str

    @classmethod
    def setUpClass(cls):
        cls.md = convert_rst_to_md(str(cls.path), cls.path.read_text())

    def test_no_rst_leftovers(self):
        prose = _strip_code(self.md)
        for pattern in RST_LEFTOVERS:
            with self.subTest(pattern=pattern.pattern):
                self.assertEqual([], pattern.findall(prose))

    def test_no_empty_blocks(self):
        blocks = self.md.split('\n\n')
        self.assertEqual([], [b for b in blocks if re.fullmatch(r'[>\s]*', b)])


class TestCPythonWhatsNew(FixtureMixin, unittest.TestCase):
    path = DATA / 'cpython' / 'Doc' / 'whatsnew' / '3.15.rst'

    def test_includes_resolved(self):
        self.assertRegex(self.md, r'(?m)^#+ Pending removal in Python 3\.16$')

    def test_nested_list(self):
        self.assertIn(
            '- The import system:\n\n  - Setting `__loader__`', self.md
        )

    def test_roles(self):
        self.assertIn(
            '[gh-148211](https://github.com/python/cpython/issues/148211)',
            self.md,
        )
        self.assertIn('`sysconfig`', self.md)
        self.assertIn('`-X lazy_imports`', self.md)

    def test_seealso(self):
        self.assertIn('> **See also**', self.md)

    def test_ref_to_list_item(self):
        # only headings have Markdown anchors: keep the text, drop the link
        self.assertIn('- More color\n', self.md)
        self.assertNotIn('<a ', self.md)

    def test_table_with_code_cells(self):
        self.assertIn('  - **Old:**\n\n    ```python\n', self.md)


class TestLinuxKernelHacking(FixtureMixin, unittest.TestCase):
    path = DATA / 'linux' / 'Documentation' / 'kernel-hacking' / 'hacking.rst'

    def test_definition_list(self):
        self.assertIn('- **No memory protection**\n\n  If you', self.md)

    def test_underscore_runs_escaped(self):
        self.assertIn(r'(\_\_attribute\_\_)', self.md)

    def test_ref_to_section(self):
        self.assertIn(
            '[bottom half lock](#local_bh_disablelocal_bh_enable)', self.md
        )


if __name__ == '__main__':
    unittest.main()
