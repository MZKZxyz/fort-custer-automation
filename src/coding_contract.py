"""Narrow compile-comment proposal contract. No tools, paths opened, or execution.

Edits are exact replacements against controller-retained pinned bytes. This first
contract permits only insertion of standalone // comment lines immediately above
compile; executable bytes (including indentation) must remain identical.
"""
import re

from src import orchestration_evidence as e
from src.local_runner import manifest

SCHEMA = 'coding-compile-comment-v1'
FILE = 'tools/maze-analyzer/solver.js'
MAXIMUM = 16384
ANCHOR = re.compile(r'(?m)^[ \t]*(?:export )?function compile\(')


def prompt(spec, files):
    e.require(spec['allowed'] == [FILE] and FILE in files,
              'Compile comment file scope required')
    source = files[FILE][1].decode('utf-8')
    e.require(len(ANCHOR.findall(source)) == 1, 'Unique compile declaration required')
    value = dict(schema=SCHEMA, source=spec['source'], source_manifest=manifest(files),
                 instructions=spec['prompt'], file=FILE, content=source,
                 response=dict(old='exact unique source substring',
                               new='replacement preserving executable bytes and indentation'))
    return ('Return only a JSON object with exactly old and new strings. Add explanatory '
            'standalone // comment lines immediately above compile(). Preserve all existing '
            'bytes. No tools, commands, other files, or publication.\n'+e.canonical(value))


def apply(raw, files, *, source_manifest, allowed):
    e.require(allowed == [FILE] and source_manifest == manifest(files),
              'Pinned source or permitted files mismatch')
    e.require(type(raw) is bytes and 0 < len(raw) <= MAXIMUM, 'Coding response bound')
    edit = e.decode(raw)
    e.require(isinstance(edit, dict) and set(edit) == {'old', 'new'} and
              all(isinstance(edit[k], str) and edit[k] for k in edit),
              'Coding replacement contract required')
    old, new = edit['old'], edit['new']
    source = files[FILE][1].decode('utf-8')
    e.require(source.count(old) == 1 and old != new, 'Exact unique replacement required')
    candidate = source.replace(old, new, 1)
    anchors = list(ANCHOR.finditer(source))
    e.require(len(anchors) == 1, 'Unique compile declaration required')
    offset = anchors[0].start()
    prefix, suffix = source[:offset], source[offset:]
    e.require(candidate.startswith(prefix) and candidate.endswith(suffix),
              'Executable source changed')
    addition = candidate[len(prefix):len(candidate)-len(suffix)]
    lines = addition.splitlines(keepends=True)
    e.require(0 < len(lines) <= 16 and all(
        re.fullmatch(r'[ \t]*//[^\r\n\x00-\x08\x0b-\x1f\u2028\u2029]*\n', line)
        for line in lines), 'Only standalone compile comments permitted')
    result = dict(files)
    result[FILE] = (files[FILE][0], candidate.encode('utf-8'))
    return result
