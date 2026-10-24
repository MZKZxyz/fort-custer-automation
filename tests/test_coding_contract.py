"""Offline adversarial contract checks; these responses are synthetic."""
import unittest

from src import coding_contract as c, orchestration_evidence as e
from src.local_runner import manifest


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.source = ('const header = 1;\n\n'
                       'export function compile(rows) {\n'
                       '  return rows;\n}\n')
        self.files = {c.FILE: (0o644, self.source.encode()),
                      'test/analyzer.test.js': (0o644, b'// retained\n')}

    def apply(self, old, new, **kwargs):
        return c.apply(e.canonical(dict(old=old, new=new)).encode(), self.files,
                       source_manifest=kwargs.get('source_manifest', manifest(self.files)),
                       allowed=kwargs.get('allowed', [c.FILE]))

    def test_multiline_and_indentation_preserving_replacements(self):
        for old in ('export function compile(rows) {', self.source):
            new = old.replace('export function compile',
                              '// Compile the supplied rows.\n// Preserve their order.\n'
                              'export function compile')
            out = self.apply(old, new)
            self.assertEqual(out['test/analyzer.test.js'], self.files['test/analyzer.test.js'])
            self.assertEqual(out[c.FILE][1], self.source.replace(
                'export function compile', '// Compile the supplied rows.\n'
                '// Preserve their order.\nexport function compile').encode())

    def test_indented_declaration_keeps_original_indentation(self):
        source = b'  export function compile(rows) {\n    return rows;\n  }\n'
        files = {c.FILE: (0o644, source)}
        edit = e.canonical(dict(old='export function compile(rows) {',
            new='// Compile the rows.\n  export function compile(rows) {')).encode()
        out = c.apply(edit, files, source_manifest=manifest(files), allowed=[c.FILE])
        self.assertEqual(out[c.FILE][1], b'  // Compile the rows.\n'+source)

    def test_executable_or_indentation_change_rejected(self):
        for old, new in [('  return rows;', 'return rows;'),
                         ('return rows;', 'return [];'),
                         ('export function compile', '// comment\n export function compile'),
                         ('const header = 1;', '// comment\nconst header = 1;')]:
            with self.subTest(new=new), self.assertRaises(ValueError): self.apply(old, new)

    def test_comment_escape_and_directive_rejected(self):
        for comment in ('// text\u2028throw Error();\n', '// text\r\n',
                        '/* comment */\n', '// text\nthrow Error();\n',
                        '// text\n\n', '// text\x00\n'):
            with self.subTest(comment=comment), self.assertRaises(ValueError):
                self.apply('export function compile', comment+'export function compile')

    def test_reviewed_replacements_cannot_add_shell_or_arbitrary_statements(self):
        contract = dict(validation='throws-test-v1',symbols=['compile'],old='// anchor')
        safe = "// anchor\ntest('missing exit', () => {\n  assert.throws(() => compile([\"S \"]));\n});"
        c.safe_replacement(contract,safe)
        for value in (safe+"\nprocess.exit(0);", safe.replace('compile(', 'eval('),
                      safe.replace('["S "]','[process.env]'), safe.replace("'missing exit'","'x');evil('//")):
            with self.assertRaises(ValueError): c.safe_replacement(contract,value)
        arithmetic = dict(validation='numeric-expression-v1',symbols=['width','height'])
        c.safe_replacement(arithmetic,'width * height + 1')
        for value in ('process.exit(0)','width.constructor','width(height)','width++','width; height',
                      'width ** height','width // height','/width/','width height','(width + height'):
            with self.assertRaises(ValueError): c.safe_replacement(arithmetic,value)

    def test_source_file_and_contract_mismatch(self):
        for kwargs in (dict(source_manifest='0'*64), dict(allowed=[c.FILE, 'other.js'])):
            with self.assertRaises(ValueError):
                self.apply('export function compile', '// text\nexport function compile', **kwargs)
        for raw in (b'{"old":"missing","new":"// text"}', b'{"approved":true}',
                    b'{"old":"x","new":"y","file":"other.js"}', b'{}', b'x'*16385):
            with self.assertRaises(ValueError):
                c.apply(raw, self.files, source_manifest=manifest(self.files), allowed=[c.FILE])


if __name__ == '__main__':
    unittest.main()
