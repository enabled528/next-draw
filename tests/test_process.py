from pathlib import Path
import sys
import time

import pytest

from next_draw.jobs import JobManager


WORKER = '''import json,sys,time
for line in sys.stdin:
    game=json.loads(line)['game']
    print(json.dumps({'kind':'progress','stage':'model','message':'Loading'}),flush=True)
    if game=='ssq': time.sleep(30)
    print(json.dumps({'kind':'result','result':{'game':game}}),flush=True)
'''


def terminal(manager, job_id):
    until = time.monotonic() + 4
    while time.monotonic() < until:
        state = manager.get(job_id)
        if state['status'] in ['complete', 'failed', 'cancelled']: return state
        time.sleep(.02)
    raise AssertionError('stalled model retained the worker')


@pytest.mark.parametrize('cancel', [False, True])
def test_stalled_model_is_terminated_and_worker_capacity_recovers(tmp_path, cancel):
    from next_draw.process import ProcessPipeline
    pipeline = ProcessPipeline(tmp_path, command=[sys.executable, '-u', '-c', WORKER])
    manager = JobManager(tmp_path, pipeline, timeout_seconds=.5)
    try:
        job = manager.submit('ssq', 'stalled-worker')
        if cancel:
            until = time.monotonic() + 2
            while manager.get(job['id'])['stage'] != 'model' and time.monotonic() < until: time.sleep(.01)
            manager.cancel(job['id'])
        assert terminal(manager, job['id'])['status'] == ('cancelled' if cancel else 'failed')
        recovered = terminal(manager, manager.submit('dlt', 'recovered-worker')['id'])
        assert recovered['status'] == 'complete' and recovered['result']['game'] == 'dlt'
    finally: manager.close()
