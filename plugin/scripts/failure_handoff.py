"""Persist failed work for a replacement worker; never executes recorded evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from model_routing import route

IDENTITY = ('task_id', 'run_id', 'ac_id', 'issue_id')
DETAILS = ('worker', 'model', 'summary', 'attempted', 'changed_files', 'checks', 'remaining', 'recorded_by')


def identity(data):
    if not isinstance(data, dict):
        raise ValueError('expected an object')
    result = {key: data.get(key) for key in IDENTITY}
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        raise ValueError('task/run/AC/issue identity required')
    return result


def prefix(data):
    return hashlib.sha256(json.dumps(identity(data), sort_keys=True).encode()).hexdigest()


def validate(record):
    identity(record)
    if set(record) != set(IDENTITY + DETAILS + ('attempt',)):
        raise ValueError('unexpected or missing record fields')
    if type(record['attempt']) is not int or not 1 <= record['attempt'] <= 3:
        raise ValueError('attempt must be 1..3')
    for key in ('worker', 'model', 'summary', 'remaining'):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError(f'{key} must be nonblank')
    for key in ('attempted', 'changed_files', 'checks'):
        if not isinstance(record[key], list) or any(not isinstance(v, str) or not v.strip() for v in record[key]):
            raise ValueError(f'{key} must be a list of nonblank strings')
    if not record['checks']:
        raise ValueError('checks must include failure or observed crash evidence')
    if record['recorded_by'] not in ('worker', 'coordinator'):
        raise ValueError('invalid recorded_by')


def history(directory, data):
    expected = identity(data)
    records = []
    for path in sorted(Path(directory).glob(prefix(data) + '-*.json')):
        if path.is_symlink():
            raise ValueError('symlink record refused')
        record = json.loads(path.read_text())
        validate(record)
        if identity(record) != expected or record['attempt'] != len(records) + 1:
            raise ValueError('mismatched identity or noncontiguous history')
        if path.name != f"{prefix(data)}-{record['attempt']}.json":
            raise ValueError('invalid record filename')
        records.append((path, record))
    return records


def record_failure(directory, data):
    validate(data)
    records = history(directory, data)
    if data['attempt'] != len(records) + 1:
        raise ValueError('attempt already recorded or out of sequence')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{prefix(data)}-{data['attempt']}.json"
    # Publish complete bytes exclusively: concurrent writers cannot replace evidence.
    fd, temporary = tempfile.mkstemp(prefix='.handoff-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    finally:
        os.unlink(temporary)
    return {'action': 'recorded', 'path': str(target.resolve()), 'attempt': data['attempt']}


def resume(directory, data):
    if set(data) - set(IDENTITY + ('impact', 'recovery', 'available_models')):
        raise ValueError('unexpected resume field; attempt count comes from history')
    records = history(directory, data)
    if not records:
        raise ValueError('no failure history for this task/run/AC/issue')
    decision = route({key: data[key] for key in ('impact', 'recovery', 'available_models') if key in data}
                     | {'failed_attempts': len(records)})
    return decision | {'identity': identity(data), 'failed_attempts': len(records),
                       'handoff_paths': [str(path.resolve()) for path, _ in records]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('record', 'resume'))
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
        result = (record_failure if args.command == 'record' else resume)(args.directory, data)
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({'action': 'blocked', 'reason': str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result['action'] in ('recorded', 'spawn') else 1


if __name__ == '__main__':
    sys.exit(main())
