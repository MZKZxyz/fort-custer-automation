"""Future narrow function contract; synthetic receivers only, no host operations."""
from pathlib import PurePosixPath
from src import orchestration_evidence as e

TOOLS = [dict(type='function', name='propose_file',
    description='Propose replacement text for one reviewed source file; never execute.', strict=True,
    parameters=dict(type='object', properties=dict(path=dict(type='string'), content=dict(type='string')),
                    required=['path','content'], additionalProperties=False))]


class SyntheticReceiver:
    def __init__(self, reviewed_files):
        e.require(isinstance(reviewed_files, dict) and 0 < len(reviewed_files) <= 16, 'Manifest required')
        for path, digest in reviewed_files.items():
            e.require(isinstance(path, str) and path == str(PurePosixPath(path)) and
                not PurePosixPath(path).is_absolute() and '..' not in PurePosixPath(path).parts and
                e.sha(digest), 'Unsafe source manifest')
        self.files = dict(reviewed_files)
        self.manifest = e.digest(self.files)

    def receive(self, raw, *, source_manifest):
        e.require(source_manifest == self.manifest and type(raw) is bytes and len(raw) <= 16384,
                  'Source binding or tool ceiling')
        call = e.decode(raw)
        e.require(isinstance(call, dict) and set(call) == {'type','name','arguments'} and
                  call['type'] == 'function_call' and call['name'] == 'propose_file' and
                  isinstance(call['arguments'], str), 'Unknown function schema')
        args = e.decode(call['arguments'])
        e.require(isinstance(args, dict) and set(args) == {'path','content'} and
                  isinstance(args['path'], str) and args['path'] in self.files and
                  isinstance(args['content'], str) and len(args['content'].encode()) <= 8192,
                  'Invalid function arguments')
        # Never open paths, invoke processes, publish, or return model-controlled text.
        return dict(synthetic=True, executed=False, proposal_digest=e.digest(args), manifest=self.manifest)


def executable_receiver(*args, **kwargs):
    raise ValueError('Verified isolated receiver unavailable; executable model tools blocked')
