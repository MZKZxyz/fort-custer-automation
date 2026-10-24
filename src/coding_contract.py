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
SOURCE = 'c4f480abb309a7a4d141b20ab462552a868ef0e3'
INSTRUCTIONS = ('Add one explanatory comment above compile describing its existing behavior. '
                'Preserve all executable code and behavior.')
USAGE_POLICY = 'supervised-sol-low-one-request'
REVIEWED_USAGE = 'supervised-sol-low-reviewed-edit-v1'
SPEND_CENTS = 531
MAXIMUM = 16384
ANCHOR = re.compile(r'(?m)^[ \t]*(?:export )?function compile\(')


def reviewed_contract(entry):
    from src.local_catalog import path_ok
    c = entry.get('edit_contract')
    e.require(isinstance(c, dict) and set(c) == {'schema','path','old','maximum_new_bytes','validation','symbols'} and
              c['schema'] == 'bounded-replacement-v1' and path_ok(c['path']) and
              c['validation'] in {'throws-test-v1','numeric-expression-v1'} and
              isinstance(c['symbols'],list) and 0 < len(c['symbols']) <= 16 and
              all(isinstance(v,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',v) for v in c['symbols']) and
              c['path'].endswith(('.js','.mjs','.cjs')) and entry['allowed'] == [c['path']] and
              isinstance(c['old'], str) and 0 < len(c['old'].encode()) <= 8192 and
              type(c['maximum_new_bytes']) is int and 0 < c['maximum_new_bytes'] <= 8192 and
              entry['limits']['api_spend_cents'] == SPEND_CENTS and
              type(entry['limits']['api_spend_cents']) is int and
              any(q['argv'] == ['node','--check',c['path']] for q in entry['checks']) and
              any(q['argv'][1] == '--test' for q in entry['checks']),
              'Explicit bounded replacement and independent syntax/tests required')
    e.require(c['validation'] != 'throws-test-v1' or len(c['symbols']) == 1, 'One reviewed callable required')
    return c


def safe_replacement(c, new):
    if c['validation'] == 'numeric-expression-v1':
        tokens = re.findall(r'[A-Za-z][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?|[()+*/%\-]|\s+', new)
        e.require(''.join(tokens) == new and len(tokens) <= 128 and
                  not any(v in new for v in ('++','--','**','//','/*')) and
                  all(not re.match(r'[A-Za-z]',t) or t in c['symbols'] for t in tokens) and
                  not re.search(r'(?:[A-Za-z0-9_]|\))\s*\(',new), 'Only reviewed arithmetic expressions permitted')
        return
    e.require(new.startswith(c['old']+'\n'), 'Existing reviewed anchor must be preserved')
    addition = new[len(c['old'])+1:]
    pattern = (r"test\('[A-Za-z0-9 ,.-]{1,120}', \(\) => \{\n  assert\.throws\(\(\) => "+
               re.escape(c['symbols'][0])+r"\((.+)\)\);\n\}\);")
    match = re.fullmatch(pattern,addition)
    e.require(match is not None, 'Only one reviewed throws-test addition permitted')
    arguments = e.decode(match[1])
    def data(value, depth=0):
        return (depth <= 4 and (value is None or type(value) in (bool,int,float,str) or
                isinstance(value,list) and len(value) <= 128 and all(data(v,depth+1) for v in value)))
    e.require(isinstance(arguments,list) and len(arguments) <= 16 and data(arguments) and
              match[1] == e.canonical(arguments), 'Only canonical JSON argument data permitted')


def catalog_task(entry):
    if entry['limits']['usage_policy'] == REVIEWED_USAGE:
        reviewed_contract(entry)
        return
    e.require('edit_contract' not in entry, 'Legacy contract cannot be reinterpreted')
    e.require(entry['source'] == SOURCE and entry['repo'] == 'fort-custer-server' and
              entry['repository'] == 'MZKZxyz/fort-custer-server' and
              entry['allowed'] == [FILE] and entry['instructions'] == INSTRUCTIONS and
              entry['limits']['usage_policy'] == USAGE_POLICY and
              type(entry['limits']['api_spend_cents']) is int and
              entry['limits']['api_spend_cents'] == SPEND_CENTS,
              'Pinned coding task and explicit API spend approval required')
    e.require(sorted(c['argv'] for c in entry['checks']) == sorted([
        ['node', '--check', FILE], ['node', '--test', 'test/analyzer.test.js']]),
        'Exact comment task QA required')


def prompt(spec, files):
    if spec['limits']['usage_policy'] == REVIEWED_USAGE:
        c = reviewed_contract(spec['task'])
        source = files[c['path']][1].decode('utf-8')
        e.require(source.count(c['old']) == 1, 'Unique reviewed replacement anchor required')
        return ('Return only a JSON object with exactly old and new strings. Replace only the '
                'reviewed anchor. No tools, commands, other files or publication.\n'+e.canonical(dict(
                    schema=c['schema'], contract=c, source=spec['source'], source_manifest=manifest(files),
                    instructions=spec['prompt'], file=c['path'], content=source,
                    grammar=("Preserve old then newline then exactly: test('LABEL', () => {\n  assert.throws(() => "+
                             c['symbols'][0]+'(CANONICAL_JSON_ARGUMENT_ARRAY));\n});'
                             if c['validation'] == 'throws-test-v1' else
                             'Only arithmetic over reviewed symbols and numbers; no calls or statements'))))
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


def apply(raw, files, *, source_manifest, allowed, edit_contract=None):
    if edit_contract is not None:
        c = edit_contract
        e.require(type(raw) is bytes and 0 < len(raw) <= MAXIMUM and
                  allowed == [c['path']] and source_manifest == manifest(files), 'Reviewed replacement binding')
        edit = e.decode(raw)
        e.require(isinstance(edit, dict) and set(edit) == {'old','new'} and
                  edit['old'] == c['old'] and isinstance(edit['new'], str) and
                  0 < len(edit['new'].encode()) <= c['maximum_new_bytes'] and edit['old'] != edit['new'],
                  'Out-of-contract replacement')
        safe_replacement(c,edit['new'])
        source = files[c['path']][1].decode('utf-8')
        e.require(source.count(edit['old']) == 1, 'Unique exact source anchor required')
        result = dict(files)
        result[c['path']] = (files[c['path']][0], source.replace(edit['old'], edit['new'], 1).encode())
        return result
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
