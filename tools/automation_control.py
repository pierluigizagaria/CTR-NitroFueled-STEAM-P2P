"""Inspect upstreams, latch failures, and notify the repository owner."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path

import automation_state as state_store
from prepare_upstream_update import commit, latest

MARKER = '<!-- ctrnf-p2p-automatic-release-failure -->'
MODES = ('auto', 'retry', 'resume', 'verify')


def is_incident(issue):
    return (issue.get('user', {}).get('login') == 'github-actions[bot]'
            and MARKER in (issue.get('body') or '') and not issue.get('pull_request'))


def save(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')


def choose_action(mode, state, changed=False):
    status = state.get('status') if state else None
    if mode == 'verify':
        return 'build'
    if mode == 'resume':
        if status != 'pending':
            raise ValueError('Resume requires a pending publication; use retry for a failed build')
        return 'resume'
    if status == 'pending':
        if mode == 'retry':
            raise ValueError('A publication is pending; resume its original artifacts first')
        return 'skip'
    if status == 'blocked' and mode == 'auto':
        return 'skip'
    if status == 'blocked' and mode == 'retry':
        return 'build'
    return 'build' if changed else 'skip'


def outputs(values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as file:
            for name, value in values.items():
                if '\n' in str(value) or '\r' in str(value):
                    raise ValueError('Multiline workflow output refused')
                file.write(f'{name}={value}\n')


def inspect(directory, mode):
    directory = Path(directory)
    config = json.loads(Path('automation.json').read_text(encoding='utf-8'))
    lock = json.loads(Path('distribution-lock.json').read_text(encoding='utf-8'))
    inspection = {'schema_version': 1, 'mode': mode, 'base_revision': commit('.', 'HEAD'),
                  'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                  'version': config['release_tag'], 'run_id': os.environ.get('GITHUB_RUN_ID'),
                  'run_url': f"https://github.com/{state_store.repository()}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"}
    save(directory / 'inspection.json', inspection)
    state, state_revision = state_store.read_state()
    inspection['state_revision'] = state_revision
    action = choose_action(mode, state)
    reports = {}
    if action == 'resume':
        plan = state['plan']
        save(directory / 'plan.json', plan)
        inspection.update(version=plan['version'], source_run_id=state['source_run_id'])
    elif not (state and state['status'] in {'blocked', 'pending'} and mode == 'auto'):
        for channel, pin in sorted(lock['channels'].items()):
            if mode == 'verify':
                reports[channel] = {'schema_version': 1, 'status': 'unchanged', 'channel': channel,
                                    'upstream_repository': pin['upstream']['repository'],
                                    'upstream_tag': pin['upstream']['tag'],
                                    'upstream_revision': pin['upstream']['revision'],
                                    'locked_upstream': pin['upstream'], 'read_only': True}
            else:
                reports[channel] = latest('distribution-lock.json', channel)
        action = choose_action(mode, state, any(item['status'] == 'changed' for item in reports.values()))
        save(directory / 'reports.json', reports)
    inspection.update(action=action, reports=reports)
    inspection['verify'] = (mode == 'verify' or
                            (mode == 'retry' and action == 'build' and
                             not any(item['status'] == 'changed' for item in reports.values())))
    inspection['fingerprint'] = hashlib.sha256(json.dumps(
        {'base': inspection['base_revision'], 'reports': reports}, sort_keys=True).encode()).hexdigest()
    save(directory / 'inspection.json', inspection)
    matrix = {'include': [{'channel': channel, 'repository': config['host_repository'],
                           'revision': pin['revision']} for channel, pin in sorted(lock['channels'].items())]}
    outputs({'action': action, 'version': inspection['version'], 'matrix': json.dumps(matrix),
             'artifact_run_id': inspection.get('source_run_id', inspection['run_id']),
             'verify': str(inspection['verify']).lower()})
    reason = ('Stopped by the previous failure/pending publication; run retry or resume after review.'
              if action == 'skip' and state and state['status'] != 'completed'
              else 'No new stable upstream release.' if action == 'skip'
              else 'Reusing the original tested artifacts.' if action == 'resume'
              else 'Build and test both channels before any publication.')
    print(reason)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(f'Automation: **{action}**. {reason}\n\n')
            for channel, report in reports.items():
                summary.write(f"- {channel}: {report['status']} — {report['upstream_tag']} ({report['upstream_revision']})\n")
    return inspection


def failure_document(previous, inspection, plan, run_url, failed):
    fingerprint = (plan or {}).get('fingerprint') or inspection.get('fingerprint') or inspection.get('base_revision', 'inspection')
    incident = {'fingerprint': fingerprint, 'run_url': run_url, 'failed_jobs': failed}
    if previous and previous['status'] == 'pending':
        if plan and previous['plan']['fingerprint'] != plan['fingerprint']:
            raise ValueError('A different publication is pending; refusing to replace its recovery state')
        document = dict(previous)
    elif previous and previous['status'] == 'completed' and plan and previous.get('plan', {}).get('fingerprint') == fingerprint:
        # Completion is authoritative if the process failed only after recording it.
        return None
    else:
        document = {'schema_version': 1, 'status': 'blocked', 'inspection': inspection,
                    'plan': plan, 'previous_completion': (previous or {}).get('completion')}
    document['incident'] = incident
    if previous and previous.get('notification'):
        document['notification'] = previous['notification']
    return document


def notify(directory, jobs):
    directory = Path(directory)
    config = json.loads(Path('automation.json').read_text(encoding='utf-8'))
    def optional(name):
        path = directory / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    inspection, plan = optional('inspection.json'), optional('plan.json') or None
    failed = sorted(name for name, value in jobs.items() if value.get('result') in {'failure', 'cancelled'})
    if not failed:
        return
    repo = state_store.repository()
    run_url = f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    previous, old_revision = state_store.read_state()
    document = failure_document(previous, inspection, plan, run_url, failed)
    if document is None:
        return
    # Latch before sending the notification so a notification-service error never
    # leaves the scheduled build retrying a known failure unattended.
    state_revision = state_store.write_state(document, old_revision)
    fingerprint = document['incident']['fingerprint']
    body = (MARKER + '\n\nAutomatic P2P updates have stopped.\n\n'
            f"Failed stage: **{', '.join(failed)}**. [Open the workflow log]({run_url}).\n\n")
    for channel, item in (plan or {}).get('channels', {}).items():
        body += f"- {channel}: {item['upstream']['tag']} / `{item['upstream']['revision']}`\n"
    if document['status'] == 'pending':
        body += ('\nPublication was interrupted. The saved transaction retains the exact artifacts and revisions. '
                 'Use the workflow **resume** mode; do not rebuild or replace existing asset names.\n')
    else:
        body += ('\nNo publication step ran. Fix the conflict or failing checks, then run the workflow '
                 'in **retry** mode. Scheduled runs stay stopped until a retry succeeds.\n')
    pages = state_store.api('repos/' + repo + '/issues?state=open&per_page=100')
    existing = next((issue for issue in pages if is_incident(issue)), None)
    if existing:
        issue_number = existing['number']
        state_store.api(f'repos/{repo}/issues/{issue_number}', {'body': body}, method='PATCH')
        if document.get('notification', {}).get('fingerprint') != fingerprint:
            state_store.api(f'repos/{repo}/issues/{issue_number}/comments',
                            {'body': f"@{config['notification_assignee']} A different automatic update stopped. [Workflow details]({run_url})."})
    else:
        issue = state_store.api('repos/' + repo + '/issues', {
            'title': 'P2P automatic release stopped', 'body': body,
            'assignees': [config['notification_assignee']]})
        issue_number = issue['number']
    document['notification'] = {'issue_number': issue_number, 'fingerprint': fingerprint}
    state_store.write_state(document, state_revision)
    print(f'https://github.com/{repo}/issues/{issue_number}')


def finish(directory):
    """Close the incident only after its publication or verification succeeded."""
    plan = json.loads((Path(directory) / 'plan.json').read_text(encoding='utf-8'))
    inspection = json.loads((Path(directory) / 'inspection.json').read_text(encoding='utf-8'))
    previous, ref = state_store.read_state()
    repo = state_store.repository()
    run_url = f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    if plan['verify']:
        # Verification cannot clear a failed real update or a pending publication.
        if (not previous or previous['status'] != 'blocked'
                or (previous.get('inspection', {}).get('mode') != 'verify'
                    and inspection.get('mode') != 'retry')):
            return
        state_store.write_state({'schema_version': 1, 'status': 'completed', 'plan': plan,
                                 'verification': {'run_url': run_url, 'published': False}}, ref)
        message = f'Current pinned builds and publisher verification passed. No release was published. [Run]({run_url}).'
    else:
        if (not previous or previous['status'] != 'completed'
                or previous.get('plan', {}).get('fingerprint') != plan['fingerprint']):
            raise ValueError('Cannot resolve an incident without its completed publication')
        message = f'Both channel packages were tested and publication completed. [Run]({run_url}).'
    issues = state_store.api('repos/' + repo + '/issues?state=open&per_page=100')
    for issue in issues:
        if is_incident(issue):
            path = f"repos/{repo}/issues/{issue['number']}"
            state_store.api(path + '/comments', {'body': message})
            state_store.api(path, {'state': 'closed', 'state_reason': 'completed'}, method='PATCH')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('inspect')
    check.add_argument('--mode', choices=MODES, default='auto')
    check.add_argument('--directory', default='out/automation')
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--directory', default='out/automation')
    prepare.add_argument('--host-source', required=True)
    failed = sub.add_parser('notify')
    failed.add_argument('--directory', default='out/automation')
    finished = sub.add_parser('finish')
    finished.add_argument('--directory', default='out/automation')
    args = parser.parse_args()
    if args.command == 'inspect':
        inspect(args.directory, args.mode)
    elif args.command == 'prepare':
        import automation_prepare
        directory = Path(args.directory)
        inspection = json.loads((directory / 'inspection.json').read_text(encoding='utf-8'))
        reports = json.loads((directory / 'reports.json').read_text(encoding='utf-8'))
        try:
            plan = automation_prepare.plan(Path('.'), Path(args.host_source), reports,
                                           inspection['timestamp'], verify=inspection['verify'])
        except (ValueError, OSError, KeyError) as error:
            # Retain conflict paths and Git diagnostics as source evidence.
            save(directory / 'failure.json', {'schema_version': 1, 'error': str(error),
                                             'candidate': getattr(error, 'candidate', None)})
            raise
        save(directory / 'plan.json', plan)
    elif args.command == 'notify':
        notify(args.directory, json.loads(os.environ['JOB_RESULTS']))
    else:
        finish(args.directory)


if __name__ == '__main__':
    main()
