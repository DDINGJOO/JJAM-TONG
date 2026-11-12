#!/usr/bin/env python3
"""Verify explicit synthetic context across three already-running loopback fixtures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request
import uuid


MODES = {'mvc-platform': 28280, 'mvc-virtual': 28281, 'netty': 28282}


def request(base, path, body=None, parent=None, timeout=15):
    if path == '/probe/requests' and body is not None:
        # Boot 4/Jackson 3 rejects missing primitive record components.
        body = {'delayMillis': 0, 'retryFailures': 0, 'dropHeader': False,
                'failAfterInsert': False, **body}
    headers = {'Content-Type': 'application/json'}
    if parent is not None:
        headers['traceparent'] = parent
    req = urllib.request.Request(base + path, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_for(check, seconds=40):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        time.sleep(.1)
    raise AssertionError(f'Timed out waiting for fixture condition: {last!r}')


def traceparent():
    return f'00-{uuid.uuid4().hex}-{uuid.uuid4().hex[:16]}-01'


def effect_count(event):
    return sum(row['applied_count'] for row in event['effects'])


def validate_event(event, parent, digest, build_id, missing=False):
    assert isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest), 'Invalid artifact digest'
    assert isinstance(build_id, str) and build_id.strip(), 'Missing build identity'
    assert len(event['outbox']) == 1 and event['outbox'][0]['published'] is True, event
    assert event['outbox'][0]['traceparent'] == parent
    assert effect_count(event) == 1, event
    assert event['attempts'], 'Missing consumer attempt evidence'
    stages = {row['stage'] for row in event['observations']}
    assert {'request-ingress', 'request-work', 'request-clean', 'outbox-publish',
            'publisher-clean', 'consumer-attempt', 'consumer-clean'} <= stages, stages
    for row in event['observations']:
        assert row['artifact_sha256'] == digest, row
        assert row['build_id'] == build_id, row
        assert row['context_before'] is None, f'Context leaked into a stage: {row}'
        if row['stage'].endswith('-clean'):
            assert row['context_after'] is None, f'Context not cleaned: {row}'
        else:
            expected = None if missing and row['stage'] == 'consumer-attempt' else parent
            assert row['traceparent'] == expected, f'Wrong context: {row}'
    for row in event['attempts']:
        assert row['traceparent'] == (None if missing else parent), row


def compare_mode(mode, base, expected_revision):
    status, runtime = request(base, '/probe/runtime')
    assert status == 200 and runtime['mode'] == mode, (status, runtime)
    assert runtime['manualContextProbe'] is True
    evidence = runtime['buildEvidence']
    identity = evidence['build']
    assert evidence['artifactDigestVerified'] is True and identity['revision'] == expected_revision
    assert evidence['analysisLinkStatus'] == 'UNRESOLVED'
    digest = identity['artifactSha256']
    build_id = identity['build']
    assert runtime['admissionLimit'] == 4 and runtime['dbPool']['limit'] == 2
    results = []

    def event(event_id):
        status, data = request(base, '/probe/events/' + event_id)
        assert status == 200, (status, data)
        assert data['mode'] == mode, data
        return data

    def settled(event_id, attempts=1):
        def completed():
            data = event(event_id)
            return (data if effect_count(data) == 1
                    and len(data['attempts']) >= attempts
                    and any(row['stage'] == 'consumer-clean' for row in data['observations'])
                    and data['outbox'] and data['outbox'][0]['published'] else None)
        return wait_for(completed)

    def create(body=None, parent=None):
        payload = {'eventId': str(uuid.uuid4()), **(body or {})}
        parent = parent or traceparent()
        status, response = request(base, '/probe/requests', payload, parent)
        assert status == 201, (status, response)
        assert response['eventId'] == payload['eventId'] and response['traceparent'] == parent
        assert response['redisRoundTrip'] is True
        return response, parent

    # Distinct concurrent contexts exercise reused worker and Kafka callback threads.
    with ThreadPoolExecutor(max_workers=3) as pool:
        created = list(pool.map(lambda _: create(), range(12)))
    for response, parent in created:
        data = settled(response['eventId'])
        validate_event(data, parent, digest, build_id)
        ingress = next(row for row in data['observations'] if row['stage'] == 'request-ingress')
        work = next(row for row in data['observations'] if row['stage'] == 'request-work')
        assert ingress['virtual'] is (mode == 'mvc-virtual'), ingress
        assert work['virtual'] is (mode == 'mvc-virtual'), work
        if mode == 'netty':
            assert ingress['thread_name'] != work['thread_name'], (ingress, work)
            assert 'reactor-http' in ingress['thread_name'], ingress
            assert 'reactor-http' not in work['thread_name'], work
    results.append({'case': 'concurrent-context-isolation', 'passed': True, 'requests': 12,
                    'concurrency': 3, 'sample': data})

    response, parent = create({'retryFailures': 2})
    data = settled(response['eventId'], 3)
    validate_event(data, parent, digest, build_id)
    assert [row['outcome'] for row in data['attempts']] == ['retryable-failure', 'retryable-failure', 'applied']
    assert len({row['attempt_no'] for row in data['attempts']}) == 3
    results.append({'case': 'two-retries-one-effect', 'passed': True, 'event': data})

    status, replay = request(base, '/probe/replay/' + response['eventId'], {})
    assert status == 200 and replay['replayed'] is True, (status, replay)
    data = settled(response['eventId'], 4)
    validate_event(data, parent, digest, build_id)
    assert data['attempts'][-1]['outcome'] == 'duplicate'
    results.append({'case': 'duplicate-one-effect', 'passed': True, 'event': data})

    response, parent = create({'dropHeader': True})
    data = settled(response['eventId'])
    validate_event(data, parent, digest, build_id, missing=True)
    try:
        validate_event(data, parent, digest, build_id)
    except AssertionError:
        detected = True
    else:
        raise AssertionError('Negative control failed: missing context was accepted as connected')
    results.append({'case': 'missing-context-negative-control', 'passed': True,
                    'false-connection-rejected': detected, 'event': data})

    failed_id = str(uuid.uuid4())
    status, failure = request(base, '/probe/requests', {'eventId': failed_id, 'failAfterInsert': True}, traceparent())
    assert status == 503 and failure['eventId'] == failed_id, (status, failure)
    data = event(failed_id)
    assert not data['outbox'] and not data['effects']
    assert any(row['stage'] == 'request-clean' and row['context_after'] is None for row in data['observations'])
    results.append({'case': 'transaction-rollback-and-cleanup', 'passed': True, 'event': data})

    # Occupy admitted work and inspect lightweight health while DB work is waiting/running.
    def slow(_):
        return request(base, '/probe/requests', {'eventId': str(uuid.uuid4()), 'delayMillis': 1000}, traceparent())
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(slow, i) for i in range(12)]
        active = wait_for(lambda: (lambda r: r if r['activeWork'] >= 4 else None)(request(base, '/probe/runtime')[1]), 10)
        started = time.monotonic()
        health_status, _ = request(base, '/probe/health')
        health_millis = round((time.monotonic() - started) * 1000, 3)
        statuses_and_bodies = [future.result() for future in futures]
    statuses = [code for code, _ in statuses_and_bodies]
    assert health_status == 200 and set(statuses) <= {201, 429} and 429 in statuses, statuses
    assert active['activeWork'] <= active['admissionLimit'] == 4
    if mode == 'netty':
        assert active['executor']['active'] <= 4 and active['executor']['queued'] <= 4, active
    for status, response in statuses_and_bodies:
        if status == 201:
            settled(response['eventId'])
    wait_for(lambda: request(base, '/probe/runtime')[1]['activeWork'] == 0)
    results.append({'case': 'slow-jdbc-bounded-admission', 'passed': True,
                    'requests': 12, 'accepted': statuses.count(201), 'rejected429': statuses.count(429),
                    'health_status': health_status, 'health_millis_single_sample': health_millis,
                    'during_load': active})

    # A client timeout is observable independently from whether server work was cancelled.
    cancelled_id = str(uuid.uuid4())
    timed_out = False
    try:
        request(base, '/probe/requests', {'eventId': cancelled_id, 'delayMillis': 1000}, traceparent(), timeout=.05)
    except (TimeoutError, socket.timeout, urllib.error.URLError):
        timed_out = True
    assert timed_out, 'Client disconnect input did not time out'
    wait_for(lambda: request(base, '/probe/runtime')[1]['activeWork'] == 0)
    time.sleep(.3)
    data = event(cancelled_id)
    assert len(data['outbox']) <= 1 and effect_count(data) <= 1
    assert any(row['stage'] == 'request-work' for row in data['observations']), data
    if data['outbox']:
        data = settled(cancelled_id)
    response, parent = create()
    validate_event(settled(response['eventId']), parent, digest, build_id)
    results.append({'case': 'client-timeout-observation', 'passed': True, 'client_timed_out': True,
                    'outbox_after_timeout': len(data['outbox']), 'effects_observed': effect_count(data),
                    'event': data, 'followup_context_clean': True, 'server_cancellation_guarantee': False})
    return {'mode': mode, 'runtime': runtime, 'scenarios': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-target-revision', required=True)
    parser.add_argument('--output', type=Path, default=Path('results/execution-comparison.json'))
    args = parser.parse_args()
    runs = []
    for mode, port in MODES.items():
        runs.append(compare_mode(mode, f'http://127.0.0.1:{port}', args.expected_target_revision))
        print(f'{mode}: {len(runs[-1]["scenarios"])} scenarios passed', flush=True)
    result = {'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'target_revision': args.expected_target_revision, 'runs': runs,
              'limitations': ['Manual synthetic context, not automatic method tracing or OTel spans',
                              'No fan-out or batch span-link validation',
                              'No Kafka commit-offset loss/rebalance or collector sampling validation',
                              'No production benchmark, AWS or Kubernetes execution']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
