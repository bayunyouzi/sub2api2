import copy
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('controller', pathlib.Path(__file__).with_name('autodeploy.py'))
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class DeploymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.work = self.root / 'autodeploy'
        self.work.mkdir()
        self.flag = self.root / 'maintenance'
        for name, value in [('ROOT', self.root), ('WORK', self.work), ('MAINTENANCE', self.flag)]:
            patcher = patch.object(controller, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.old = {
            'services': {'sub2api': {
                'image': 'migration/sub2api:20261024',
                'environment': {'TOTP_ENCRYPTION_KEY': 'same-fixed-key', 'JWT_SECRET': 'same-jwt',
                                'DATABASE_HOST': 'postgres', 'REDIS_HOST': 'redis'},
                'volumes': ['./data/sub2api:/app/data'],
            }, 'postgres': {'image': 'old-postgres'}, 'redis': {'image': 'old-redis'}},
        }
        self.metadata = {'revision': 'a' * 40, 'image': controller.IMAGE_PREFIX + 'a' * 40,
                         'image_id': 'sha256:' + 'b' * 64, 'version': '0.2.19'}
        controller.write_json(self.root / 'compose.json', self.old)
        controller.write_json(self.work / 'state.json', {'deployed_revision': 'c' * 40})
        self.calls = []

    def fake_compose(self, *args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, b'container-id\n')

    def fake_run(self, args, **kwargs):
        return subprocess.CompletedProcess(args, 0, json.dumps([{'Image': 'sha256:old'}]).encode())

    def fake_snapshot(self, directory):
        self.assertTrue(self.flag.exists())
        (directory / 'COMPLETE').touch()

    def controller_mocks(self):
        for target, replacement in [('compose', self.fake_compose), ('run', self.fake_run),
                                    ('snapshot', self.fake_snapshot)]:
            patcher = patch.object(controller, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_success_retains_credentials_and_updates_only_application(self):
        self.controller_mocks()
        with patch.object(controller, 'wait_for_app') as health:
            with patch.object(controller, 'restore') as restore:
                controller.activate(self.metadata, copy.deepcopy(self.old))
        updated = controller.read_json(self.root / 'compose.json')
        self.assertEqual(updated['services']['postgres'], self.old['services']['postgres'])
        self.assertEqual(updated['services']['redis'], self.old['services']['redis'])
        environment = updated['services']['sub2api']['environment']
        self.assertEqual(environment['TOTP_ENCRYPTION_KEY'], 'same-fixed-key')
        self.assertEqual(environment['JWT_SECRET'], 'same-jwt')
        self.assertFalse(self.flag.exists())
        self.assertFalse((self.work / 'transaction.json').exists())
        restore.assert_not_called()
        health.assert_called_once_with(self.metadata['image_id'])

    def test_backup_failure_resumes_old_app_without_restoring_database(self):
        self.controller_mocks()
        with patch.object(controller, 'snapshot', side_effect=RuntimeError('backup failed')):
            with patch.object(controller, 'wait_for_app') as health:
                with patch.object(controller, 'restore') as restore:
                    with self.assertRaisesRegex(RuntimeError, 'backup failed'):
                        controller.activate(self.metadata, self.old)
        restore.assert_not_called()
        health.assert_called_once_with('sha256:old')
        self.assertEqual(controller.read_json(self.root / 'compose.json'), self.old)
        self.assertFalse(self.flag.exists())

    def test_candidate_failure_restores_snapshot_before_reopening(self):
        self.controller_mocks()
        def health(image):
            self.assertTrue(self.flag.exists())
            if image == self.metadata['image_id']:
                raise RuntimeError('candidate unhealthy')
        with patch.object(controller, 'wait_for_app', side_effect=health):
            with patch.object(controller, 'restore') as restore:
                with self.assertRaisesRegex(RuntimeError, 'candidate unhealthy'):
                    controller.activate(self.metadata, self.old)
        restore.assert_called_once()
        self.assertEqual(controller.read_json(self.root / 'compose.json'), self.old)
        state = controller.read_json(self.work / 'state.json')
        self.assertEqual(state['deployed_revision'], 'c' * 40)
        self.assertEqual(state['failed_revision'], 'a' * 40)
        self.assertFalse(self.flag.exists())

    def test_recovery_failure_retains_maintenance_and_pauses(self):
        self.controller_mocks()
        with patch.object(controller, 'wait_for_app', side_effect=RuntimeError('unhealthy')):
            with patch.object(controller, 'restore', side_effect=RuntimeError('restore failed')):
                with self.assertRaisesRegex(RuntimeError, 'restore failed'):
                    controller.activate(self.metadata, self.old)
        self.assertTrue(self.flag.exists())
        self.assertTrue((self.work / 'PAUSED').exists())
        self.assertTrue((self.work / 'transaction.json').exists())

    def test_committed_recovery_never_rolls_back_live_writes(self):
        self.controller_mocks()
        directory = self.work / 'snapshots' / 'committed'
        directory.mkdir(parents=True)
        self.flag.touch()
        with patch.object(controller, 'restore') as restore:
            controller.recover({'snapshot': str(directory), 'phase': 'committed'})
        restore.assert_not_called()
        self.assertFalse(self.calls)
        self.assertFalse(self.flag.exists())

    def test_invalid_snapshot_is_rejected_before_database_commands(self):
        self.controller_mocks()
        directory = self.work / 'snapshot'
        directory.mkdir()
        (directory / 'COMPLETE').touch()
        (directory / 'zeabur.dump').write_bytes(b'broken dump')
        controller.write_json(directory / 'manifest.json', {'zeabur.dump': '0' * 64})
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            controller.restore(directory)
        self.assertEqual(self.calls, [])

    def test_missing_fixed_encryption_key_blocks_upgrade(self):
        self.old['services']['sub2api']['environment'].pop('TOTP_ENCRYPTION_KEY')
        with self.assertRaisesRegex(RuntimeError, 'encryption key'):
            controller.require_configuration(self.old)

    def test_recovery_rejects_path_outside_snapshot_directory(self):
        self.controller_mocks()
        with self.assertRaisesRegex(RuntimeError, 'snapshot recovery path'):
            controller.recover({'snapshot': str(self.root), 'phase': 'deploying'})
        self.assertEqual(self.calls, [])

    def test_preflight_uses_new_data_and_copies_readonly_configuration_files(self):
        config = self.root / 'config'
        config.mkdir()
        (config / 'redis.conf').write_text('appendonly no\n')
        isolated = self.work / 'test'
        isolated.mkdir()
        volumes = controller.isolated_volumes('redis', ['./data/redis:/data', './config/redis.conf:/etc/redis.conf:ro'], isolated)
        self.assertEqual(volumes[0], str(isolated / 'data/redis') + ':/data')
        self.assertEqual(volumes[1], str(isolated / 'config/redis-redis.conf') + ':/etc/redis.conf:ro')
        self.assertEqual((isolated / 'config/redis-redis.conf').read_text(), 'appendonly no\n')
        with self.assertRaisesRegex(RuntimeError, 'Unsupported preflight volume'):
            controller.isolated_volumes('redis', ['./config/redis.conf:/etc/redis.conf'], isolated)


if __name__ == '__main__':
    unittest.main()
