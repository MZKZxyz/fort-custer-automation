import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from orchestrator import schedule, read_json, ROOT

SETTINGS = read_json(ROOT/'config/settings.json')
BACKLOG = read_json(ROOT/'examples/backlog.json')

class TestPolicy(unittest.TestCase):
    def test_dryrun_and_budget(self):
        result = schedule(SETTINGS, BACKLOG)
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['merges_performed'])
        self.assertLessEqual(result['reserved_usd'], 10)
        self.assertLessEqual(len(result['selected']), 3)
    def test_exclusive_area_and_dependencies(self):
        result = schedule(SETTINGS, BACKLOG)
        ids = {x['id'] for x in result['selected']}
        self.assertIn('FC-201', ids)
        self.assertNotIn('FC-204', ids)
    def test_prior_running_reservations(self):
        result = schedule(SETTINGS, BACKLOG, already_running=[BACKLOG[0], BACKLOG[1]], already_reserved=9)
        self.assertEqual(result['selected'], [])
    def test_policy_fails_closed(self):
        import copy
        s = copy.deepcopy(SETTINGS)
        s['release']['auto_merge'] = True
        with self.assertRaises(AssertionError): schedule(s, BACKLOG)
    def test_excess_agents_rejected(self):
        import copy
        s=copy.deepcopy(SETTINGS)
        s['agents']['max_concurrent_coding']=4
        with self.assertRaises(AssertionError): schedule(s,BACKLOG)

if __name__ == '__main__': unittest.main()
