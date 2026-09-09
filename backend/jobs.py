"""Small in-process job queue for CPU-heavy desktop analyses."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
import traceback
import uuid


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='wavelab-job')
_lock = threading.Lock()
_jobs = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def submit_job(kind, function, *args, **kwargs):
    job_id = uuid.uuid4().hex
    with _lock:
        cutoff = time.monotonic() - 3600
        for stale_id in [key for key, value in _jobs.items()
                         if value.get('_finished_clock', float('inf')) < cutoff]:
            del _jobs[stale_id]
        _jobs[job_id] = {
            'id': job_id, 'kind': kind, 'state': 'queued', 'progress': 0,
            'created_at': _now(), 'started_at': None, 'finished_at': None,
            'result': None, 'error': None,
        }

    def run():
        with _lock:
            job = _jobs[job_id]
            job.update(state='running', progress=5, started_at=_now())
        try:
            result = function(*args, **kwargs)
            with _lock:
                _jobs[job_id].update(state='completed', progress=100,
                                     result=result, finished_at=_now(),
                                     _finished_clock=time.monotonic())
        except BaseException as exc:
            with _lock:
                _jobs[job_id].update(state='failed', progress=100,
                                     error=str(exc), finished_at=_now(),
                                     traceback=traceback.format_exc(),
                                     _finished_clock=time.monotonic())

    future = _executor.submit(run)
    with _lock:
        _jobs[job_id]['future'] = future
    return public_job(job_id)


def public_job(job_id):
    with _lock:
        if job_id not in _jobs:
            return None
        job = deepcopy({key: value for key, value in _jobs[job_id].items()
                        if key not in ('future', 'traceback', '_finished_clock')})
    return job


def cancel_job(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        future = job.get('future')
        if future and future.cancel():
            job.update(state='cancelled', progress=100, finished_at=_now(),
                       _finished_clock=time.monotonic())
        elif job['state'] in ('queued', 'running'):
            # Python numerical calls cannot be interrupted safely mid-call.
            job['cancel_requested'] = True
        return deepcopy({key: value for key, value in job.items()
                         if key not in ('future', 'traceback', '_finished_clock')})
