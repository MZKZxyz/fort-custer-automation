"""Verify CI failures/deadlines propagate, selections stay valid, and timings survive."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ci_runner


class RunnerTests(unittest.TestCase):
    def invoke(self, group, *extra):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        output = Path(temporary.name).resolve(strict=True)
        result = subprocess.run([sys.executable, str(ci_runner.TESTS/'ci_runner.py'), group,
            '--output', str(output), *extra], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=15)
        return result, output

    def test_pass_timings_and_optimization_mode(self):
        for group, optimize in [('full',0),('optimized-security',1)]:
            with self.subTest(group=group):
                result, output = self.invoke(group,'--names','ci_runner_cases.Cases.test_pass','ci_runner_cases.Cases.test_overwrites_id')
                self.assertEqual(result.returncode,0,result.stdout)
                self.assertIn('[RUN] ci_runner_cases.Cases.test_pass',result.stdout)
                report = json.loads((output/(group+'.timings.json')).read_text())
                self.assertEqual(report['tests'],2); self.assertEqual(report['optimize'],optimize)
                self.assertEqual(len(report['slow_tests']),2)
                self.assertGreaterEqual(report['seconds'],0)

    def test_failure_remains_nonzero(self):
        result, output = self.invoke('full','--names','ci_runner_cases.Cases.test_fail')
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads((output/'full.timings.json').read_text())['failures'],1)
        self.assertIn('intentional runner failure fixture',result.stdout)

    def test_empty_selection_cannot_pass(self):
        result, _ = self.invoke('full','--names')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Empty or duplicate test selection',result.stdout)

    def test_group_deadline_kills_worker_and_returns_failure(self):
        result, output = self.invoke('full','--timeout','1','--test-timeout','20',
                                     '--names','ci_runner_cases.Cases.test_hang')
        self.assertEqual(result.returncode,124,result.stdout)
        report = json.loads((output/'full.group.json').read_text())
        self.assertTrue(report['timed_out']); self.assertIn('[TIMEOUT]',result.stdout)

    def test_per_test_deadline_reports_current_case_and_stack(self):
        result, output = self.invoke('full','--timeout','10','--test-timeout','0.25',
                                     '--names','ci_runner_cases.Cases.test_hang')
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('[RUN] ci_runner_cases.Cases.test_hang',result.stdout)
        self.assertIn('Timeout',result.stdout)
        journal = [json.loads(line) for line in (output/'full.jsonl').read_text().splitlines()]
        self.assertEqual(journal[-1],dict(event='start',test='ci_runner_cases.Cases.test_hang'))

    def test_security_manifest_retains_old_targets_and_has_no_missing_or_duplicate_cases(self):
        previous = {'test_catalog_activation','test_live_observation','test_observation_planning',
                    'test_api_controller','test_api_response_validation','test_activation_readiness'}
        self.assertTrue(previous <= set(ci_runner.security_names()))
        selected = {case.id() for case in ci_runner.cases(ci_runner.load_suite('optimized-security'))}
        full = {case.id() for case in ci_runner.cases(ci_runner.load_suite('full'))}
        self.assertTrue(selected <= full)
        self.assertIn('test_durable_coding.DurableTests.test_stop_expired_policy_and_source_fail_closed',selected)
        self.assertIn('test_api_controller.BudgetTests.test_daily_and_lifetime_ceiling',selected)
        self.assertIn('test_grant_broker.BrokerTests.test_failed_approved_qa_never_validates',selected)


if __name__ == '__main__': unittest.main()
