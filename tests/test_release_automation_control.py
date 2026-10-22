import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import automation_control as control
import automation_state as state


class AutomationControlTests(unittest.TestCase):
    def test_only_the_automation_bot_can_own_the_reused_incident(self):
        issue = {'body': control.MARKER, 'user': {'login': 'somebody'}}
        self.assertFalse(control.is_incident(issue))
        issue['user']['login'] = 'github-actions[bot]'
        self.assertTrue(control.is_incident(issue))

    def test_stopped_schedule_does_not_retry_and_pending_requires_resume(self):
        for status in ('pending', 'blocked'):
            self.assertEqual(control.choose_action('auto', {'status': status}, True), 'skip')
        self.assertEqual(control.choose_action('retry', {'status': 'blocked'}, False), 'build')
        self.assertEqual(control.choose_action('resume', {'status': 'pending'}), 'resume')
        with self.assertRaises(ValueError):
            control.choose_action('retry', {'status': 'pending'}, True)
        with self.assertRaises(ValueError):
            control.choose_action('resume', {'status': 'blocked'})

    def test_publish_pinned_is_explicit_recovery_for_blocked_builds_but_not_pending_uploads(self):
        for status in (None, 'blocked', 'completed'):
            state = {'status': status} if status else None
            self.assertEqual(control.choose_action('publish-pinned', state, False), 'build')
        self.assertEqual(control.choose_action('auto', {'status': 'blocked'}, False), 'skip')
        with self.assertRaisesRegex(ValueError, 'pending publication'):
            control.choose_action('publish-pinned', {'status': 'pending'}, False)

    def test_publication_failure_preserves_exact_recovery_inputs(self):
        plan = {'fingerprint': 'original'}
        pending = {'schema_version': 1, 'status': 'pending', 'plan': plan,
                   'assets': [{'name': 'original.zip', 'sha256': 'exact'}], 'source_run_id': '123'}
        failed = control.failure_document(pending, {}, plan, 'run', ['publish'])
        self.assertEqual(failed['status'], 'pending')
        self.assertEqual(failed['assets'], pending['assets'])
        self.assertEqual(failed['source_run_id'], '123')
        self.assertNotIn('incident', pending)
        with self.assertRaises(ValueError):
            control.failure_document(pending, {}, {'fingerprint': 'different'}, 'run', ['publish'])

    def test_build_failure_latches_without_claiming_publication(self):
        failed = control.failure_document(None, {'base_revision': 'base'}, None, 'run', ['host'])
        self.assertEqual(failed['status'], 'blocked')
        self.assertEqual(failed['incident']['failed_jobs'], ['host'])
        self.assertIsNone(failed['plan'])

    def test_missing_or_failed_inspection_still_has_failure_fingerprint(self):
        failed = control.failure_document(None, {}, None, 'run', ['plan'])
        self.assertEqual(failed['incident']['fingerprint'], 'inspection')

    def test_completed_transaction_cannot_be_relabelled_blocked(self):
        plan = {'fingerprint': 'done'}
        completed = {'status': 'completed', 'plan': plan}
        self.assertIsNone(control.failure_document(completed, {}, plan, 'run', ['publish']))

    def test_repeated_failure_updates_one_issue_without_repeating_notification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control.save(root / 'inspection.json', {'fingerprint': 'same'})
            previous = {'status': 'blocked', 'notification': {'fingerprint': 'same', 'issue_number': 4}}
            calls = []
            def api(path, data=None, **kwargs):
                calls.append((path, data))
                if '?state=open' in path:
                    return [{'number': 4, 'body': control.MARKER, 'user': {'login': 'github-actions[bot]'}}]
                return {}
            with mock.patch.object(control.state_store, 'read_state', return_value=(previous, 'old')), \
                 mock.patch.object(control.state_store, 'write_state', return_value='new') as write, \
                 mock.patch.object(control.state_store, 'api', side_effect=api), \
                 mock.patch.dict(os.environ, {'GH_REPO': 'owner/bridge', 'GITHUB_RUN_ID': '456'}):
                control.notify(root, {'host': {'result': 'failure'}})
            self.assertEqual(write.call_args_list[0].args[0]['status'], 'blocked')
            self.assertEqual(len(calls), 2)
            self.assertFalse(any('/comments' in path for path, _ in calls))

    def test_verification_cannot_clear_a_real_publication_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control.save(root / 'plan.json', {'verify': True, 'base_revision': 'fixed'})
            control.save(root / 'inspection.json', {'mode': 'verify'})
            for status, mode in (('pending', 'auto'), ('blocked', 'retry')):
                previous = {'status': status, 'inspection': {'mode': mode}}
                with mock.patch.object(state, 'read_state', return_value=(previous, 'old')), \
                     mock.patch.object(state, 'write_state') as write, \
                     mock.patch.object(state, 'api') as api, \
                     mock.patch.dict(os.environ, {'GH_REPO': 'owner/bridge', 'GITHUB_RUN_ID': '789'}):
                    control.finish(root)
                write.assert_not_called()
                api.assert_not_called()

    def test_fixed_verification_resolves_its_own_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control.save(root / 'plan.json', {'verify': True, 'base_revision': 'fixed'})
            control.save(root / 'inspection.json', {'mode': 'verify'})
            previous = {'status': 'blocked', 'inspection': {'mode': 'verify', 'base_revision': 'old'}}
            with mock.patch.object(state, 'read_state', return_value=(previous, 'old')), \
                 mock.patch.object(state, 'write_state') as write, \
                 mock.patch.object(state, 'api', return_value=[]) as api, \
                 mock.patch.dict(os.environ, {'GH_REPO': 'owner/bridge', 'GITHUB_RUN_ID': '789'}):
                control.finish(root)
            self.assertEqual(write.call_args.args[0]['status'], 'completed')
            self.assertFalse(write.call_args.args[0]['verification']['published'])


class AutomationStateTests(unittest.TestCase):
    def test_concurrent_state_ref_is_never_overwritten(self):
        with mock.patch.object(state, 'read_state', return_value=({}, 'new')), \
             mock.patch.object(state, 'api') as api:
            with self.assertRaisesRegex(ValueError, 'concurrently'):
                state.write_state({'schema_version': 1, 'status': 'pending'}, 'old')
            api.assert_not_called()

    def test_existing_state_commit_is_fast_forward_only(self):
        calls = []
        def api(path, data=None, **kwargs):
            calls.append((path, data, kwargs))
            return {'sha': 'b' * 40}
        with mock.patch.object(state, 'read_state', return_value=({}, 'a' * 40)), \
             mock.patch.object(state, 'api', side_effect=api), \
             mock.patch.dict(os.environ, {'GH_REPO': 'owner/bridge'}):
            result = state.write_state({'schema_version': 1, 'status': 'blocked'}, 'a' * 40)
        self.assertEqual(result, 'b' * 40)
        self.assertEqual(calls[1][1]['parents'], ['a' * 40])
        self.assertEqual(calls[2][1], {'sha': 'b' * 40, 'force': False})
        self.assertEqual(calls[2][2]['method'], 'PATCH')

    def test_first_state_uses_atomic_ref_creation(self):
        calls = []
        def api(path, data=None, **kwargs):
            calls.append((path, data, kwargs))
            return {'sha': 'b' * 40}
        with mock.patch.object(state, 'read_state', return_value=(None, None)), \
             mock.patch.object(state, 'api', side_effect=api), \
             mock.patch.dict(os.environ, {'GH_REPO': 'owner/bridge'}):
            state.write_state({'schema_version': 1, 'status': 'completed'}, None)
        self.assertEqual(calls[1][1]['parents'], [])
        self.assertEqual(calls[2][1]['ref'], 'refs/heads/automation/state')
        self.assertNotIn('force', calls[2][1])


if __name__ == '__main__':
    unittest.main()
