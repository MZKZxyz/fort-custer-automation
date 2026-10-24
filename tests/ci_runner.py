"""Offline unittest groups with visible progress, durable timings and hard deadlines.

No production imports until unittest discovery; this is test infrastructure only.
The full group discovers the ordinary complete suite once. Optimized coverage is
reviewed in ci_security.json and always starts a separate Python -O interpreter.
"""
import argparse
import faulthandler
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT/'tests'
LIMITS = {'full': 1200, 'optimized-security': 480}
TEST_TIMEOUT = 180


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from cases(item)
        else: yield item


def security_names():
    document = json.loads((TESTS/'ci_security.json').read_text())
    if document.get('schema') != 1 or not document.get('groups'):
        raise ValueError('Reviewed security selection required')
    names = []
    for group in document['groups']:
        if not group.get('purpose') or not group.get('tests'):
            raise ValueError('Empty security coverage group')
        names.extend(group['tests'])
    return names


def load_suite(group, names=None):
    loader = unittest.TestLoader()
    if names is None and group == 'full': suite = loader.discover(str(TESTS))
    else: suite = loader.loadTestsFromNames(security_names() if names is None else names)
    if loader.errors: raise ValueError('\n'.join(loader.errors))
    identifiers = [test.id() for test in cases(suite)]
    if not identifiers or len(identifiers) != len(set(identifiers)):
        raise ValueError('Empty or duplicate test selection')
    return suite


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, journal, test_timeout, **kwargs):
        super().__init__(*args, **kwargs)
        self.journal, self.test_timeout = journal, test_timeout
        self.timings = []
        self.started = None

    def record(self, document):
        self.journal.write(json.dumps(document, sort_keys=True)+'\n')
        self.journal.flush()

    def startTest(self, test):
        self.started = time.perf_counter()
        self.current_id = test.id()  # Some fixtures reuse self.id for a request ID in setUp.
        self.record(dict(event='start', test=self.current_id))
        self.stream.writeln('[RUN] '+self.current_id)
        self.stream.flush()  # Visible before setUp, including a hung fixture.
        faulthandler.dump_traceback_later(self.test_timeout, exit=True)
        super().startTest(test)

    def stopTest(self, test):
        faulthandler.cancel_dump_traceback_later()
        duration = time.perf_counter()-self.started
        row = dict(event='finish', test=self.current_id, seconds=round(duration, 6))
        self.timings.append(row); self.record(row)
        self.stream.writeln('[TIME] %.3fs %s' % (duration, self.current_id))
        self.stream.flush()
        super().stopTest(test)


def worker(group, output, test_timeout, names=None):
    expected = 1 if group == 'optimized-security' else 0
    if sys.flags.optimize != expected:
        raise ValueError('Wrong Python optimization mode for CI group')
    output.mkdir(parents=True, exist_ok=True)
    print('[DISCOVERY] group=%s optimize=%s' % (group, sys.flags.optimize), flush=True)
    started = time.perf_counter()
    suite = load_suite(group, names)
    print('[SELECTED] %d tests' % suite.countTestCases(), flush=True)
    with (output/(group+'.jsonl')).open('w') as journal:
        result = unittest.TextTestRunner(verbosity=2, resultclass=lambda *a, **k:
            TimedResult(*a, journal=journal, test_timeout=test_timeout, **k)).run(suite)
    elapsed = time.perf_counter()-started
    modules = {}
    for row in result.timings:
        module = row['test'].split('.')[0]
        modules[module] = modules.get(module, 0)+row['seconds']
    slow = sorted(result.timings, key=lambda row:row['seconds'], reverse=True)[:20]
    report = dict(group=group, python=sys.version, platform=sys.platform, optimize=sys.flags.optimize,
                  seconds=elapsed, tests=result.testsRun, failures=len(result.failures),
                  errors=len(result.errors), skipped=len(result.skipped),
                  slow_tests=slow, module_seconds=modules)
    (output/(group+'.timings.json')).write_text(json.dumps(report, indent=2)+'\n')
    print('[SUMMARY] %s %.3fs tests=%d failures=%d errors=%d skipped=%d' %
          (group, elapsed, result.testsRun, len(result.failures), len(result.errors), len(result.skipped)), flush=True)
    for row in slow[:10]: print('[SLOW] %.3fs %s' % (row['seconds'], row['test']), flush=True)
    for module, seconds in sorted(modules.items(), key=lambda row:row[1], reverse=True)[:10]:
        print('[MODULE] %.3fs %s' % (seconds, module), flush=True)
    return 0 if result.wasSuccessful() else 1


def launch(group, output, timeout, test_timeout, names=None):
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable]
    if group == 'optimized-security': command.append('-O')
    command += [str(Path(__file__).resolve()), group, '--worker', '--output', str(output),
                '--test-timeout', str(test_timeout)]
    if names is not None: command += ['--names', *names]
    print('[GROUP] %s deadline=%.1fs per-test=%.1fs' % (group, timeout, test_timeout), flush=True)
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
    timed_out = False
    try:
        try: code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True; code = 124
            print('[TIMEOUT] %s exceeded %.1fs; inspect the last [DISCOVERY]/[RUN] and journal' %
                  (group, timeout), file=sys.stderr, flush=True)
    finally:
        # On failure/timeout also stop any descendants still in the worker group.
        # Candidate supervisors retain their existing independent cleanup guards.
        if timed_out or process.poll() is None or process.returncode != 0:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        process.wait()
    report = dict(group=group, seconds=time.perf_counter()-started,
                  exit_code=code, timed_out=timed_out)
    (output/(group+'.group.json')).write_text(json.dumps(report, indent=2)+'\n')
    return code if code >= 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=LIMITS)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--test-timeout', type=float, default=TEST_TIMEOUT)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--names', nargs='*', help='Explicit local diagnostic selection; CI uses reviewed groups')
    args = parser.parse_args()
    timeout = LIMITS[args.group] if args.timeout is None else args.timeout
    if not all(math.isfinite(v) and v > 0 for v in (timeout,args.test_timeout)):
        parser.error('Deadlines must be finite and positive')
    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(TESTS))
    output = args.output.absolute()
    if args.worker: return worker(args.group, output, args.test_timeout, args.names)
    return launch(args.group, output, timeout, args.test_timeout, args.names)


if __name__ == '__main__': raise SystemExit(main())
