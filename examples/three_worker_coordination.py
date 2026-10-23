"""Offline demo: temporary fixture approvals, three synthetic workers, no live adapter.

Run from the repository: python3 examples/three_worker_coordination.py
The test fixture temporarily extends repository identities inside this process;
this is not a production policy change or an approval interface.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1]/'tests')]
from test_concurrency_coordinator import Fixture
from src import concurrency_coordinator as c
from src.local_runner import LocalCLI


def main():
    f = Fixture()
    try:
        claims = [f.claim(i) for i in range(3)]
        barrier = threading.Barrier(3)
        original = c.SyntheticWorker.run
        def work(worker, checkout, authorization):
            barrier.wait(timeout=10)
            return original(worker, checkout, authorization)
        with patch.object(c.SyntheticWorker, 'run', work), patch.object(LocalCLI, 'run', side_effect=AssertionError('Live execution forbidden')):
            with ThreadPoolExecutor(3) as pool:
                list(pool.map(lambda claim:f.coordinator.run_synthetic(claim,c.SyntheticWorker()),claims))
        view = c.observations(f.config)
        rows = []
        for task, row in view['tasks'].items():
            artifact = next(x['document']['artifact'] for x in row['events'] if x['kind']=='qa')
            qa = row['events'][-1]['document']['qa']
            rows.append(dict(task=task, state=row['state'], slot=row['claim']['slot'],
                fencing_token=row['claim']['token'], workspace=artifact['workspace'],
                source_manifest=artifact['source_manifest'], candidate_manifest=artifact['candidate_manifest'],
                qa_digest=c.e.digest(qa), usage=row['usage']))
        assert len({r['workspace'] for r in rows}) == len({r['fencing_token'] for r in rows}) == 3
        assert all(r['state']=='completed' for r in rows)
        print(json.dumps(dict(schema=c.OBSERVATIONS, synthetic_only=True, live_workers_launched=0,
                             tasks=rows, aggregate=view['aggregate'], unsupported=view['unsupported']),indent=2,sort_keys=True))
    finally: f.close()


if __name__=='__main__':main()
