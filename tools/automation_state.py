"""Durable automation state on a separate Git branch, with compare-and-swap writes."""
import base64
import json
import os
import re
import subprocess

from release_support import revision

BRANCH = 'automation/state'
FILE = 'automation-state.json'


def repository():
    name = os.environ.get('GH_REPO', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
        raise ValueError('GH_REPO must identify the trusted bridge repository')
    return name


def api(path, data=None, *, method=None, missing=False):
    args = ['gh', 'api', path]
    if method:
        args += ['--method', method]
    if data is not None:
        args += ['--input', '-']
    result = subprocess.run(args, input=None if data is None else json.dumps(data),
                            text=True, capture_output=True, encoding='utf-8')
    if result.returncode:
        if missing and '(HTTP 404)' in result.stderr:
            return None
        raise ValueError('GitHub API failed: ' + result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def read_state():
    root = 'repos/' + repository()
    ref = api(root + '/git/ref/heads/' + BRANCH, missing=True)
    if ref is None:
        return None, None
    sha = revision(ref['object']['sha'])
    item = api(root + '/contents/' + FILE + '?ref=' + sha)
    if item.get('encoding') != 'base64' or item.get('size', 0) > 1024 * 1024:
        raise ValueError('Invalid automation state document')
    state = json.loads(base64.b64decode(item['content']))
    if state.get('schema_version') != 1 or state.get('status') not in {'pending', 'blocked', 'completed'}:
        raise ValueError('Unsupported automation state; manual inspection is required')
    return state, sha


def write_state(document, expected_revision):
    """Never overwrite a concurrent state change, including first-creation races."""
    if document.get('schema_version') != 1 or document.get('status') not in {'pending', 'blocked', 'completed'}:
        raise ValueError('Unsupported automation state')
    _, current = read_state()
    if current != expected_revision:
        raise ValueError('Automation state changed concurrently; refusing to overwrite it')
    root = 'repos/' + repository()
    content = json.dumps(document, indent=2, sort_keys=True) + '\n'
    tree = api(root + '/git/trees', {'tree': [
        {'path': FILE, 'mode': '100644', 'type': 'blob', 'content': content}]})
    commit = api(root + '/git/commits', {
        'message': 'Record P2P automation ' + document['status'],
        'tree': tree['sha'], 'parents': [current] if current else []})
    sha = revision(commit['sha'])
    if current:
        # The commit has the observed state as its sole parent. A competing update
        # makes this non-fast-forward, so force:false is the server-side CAS.
        api(root + '/git/refs/heads/' + BRANCH, {'sha': sha, 'force': False}, method='PATCH')
    else:
        api(root + '/git/refs', {'ref': 'refs/heads/' + BRANCH, 'sha': sha})
    return sha
