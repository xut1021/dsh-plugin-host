import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import market_install as target


ITEM = {'url': 'https://github.com/example/plugin', 'npm': 'dsh-example',
        'version': '1.2.3', 'installable': True, 'name': 'Example'}


class MarketInstallTests(unittest.TestCase):
    def test_fresh_catalog_rejects_stale_and_injected_identity(self):
        self.assertEqual(target.checked_item(ITEM, {'items': [ITEM]}), ITEM)
        with self.assertRaises(RuntimeError):
            target.checked_item({**ITEM, 'version': '0.9.0'}, {'items': [ITEM]})
        with self.assertRaises(RuntimeError):
            target.checked_item({**ITEM, 'npm': '--eval=bad'}, {'items': [ITEM]})
        bad = {**ITEM, 'npm': '--eval=bad'}
        with self.assertRaises(RuntimeError):
            target.checked_item(bad, {'items': [bad]})

    def test_running_dsh_never_fetches_or_writes(self):
        with patch.object(target.host, 'running_hosts', return_value=[{'pid': 1}]), \
             patch.object(target.market, 'fetch_catalog') as catalog, \
             patch.object(target.host, 'snapshot') as snapshot:
            with self.assertRaisesRegex(RuntimeError, '退出'):
                target.install_plugin.__wrapped__({}, ITEM)
            catalog.assert_not_called()
            snapshot.assert_not_called()

    def test_runtime_without_version_gate_is_refused(self):
        config = {'fallback_exe': 'old.exe', 'current_exe': 'new.exe'}
        with patch.object(target.host, 'probe', return_value={'compatibilityApi': False, 'plugins': []}):
            with self.assertRaisesRegex(RuntimeError, '版本检查接口'):
                target.choose_runtime(config, Path('unused'))

    def test_existing_local_dependency_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / 'profiles/desktop'
            profile.mkdir(parents=True)
            (profile / 'package.json').write_text(json.dumps({'dependencies': {ITEM['npm']: 'file:../local'}}))
            with patch.object(target.host, 'running_hosts', return_value=[]), \
                 patch.object(target.market, 'fetch_catalog', return_value={'items': [ITEM]}), \
                 patch.object(target.host, 'snapshot') as snapshot:
                with self.assertRaisesRegex(RuntimeError, '覆盖'):
                    target.install_plugin.__wrapped__({'home': temp}, ITEM)
                snapshot.assert_not_called()

    def test_verified_install_records_snapshot_without_claiming_functionality(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / 'profiles/desktop'
            profile.mkdir(parents=True)
            (profile / 'package.json').write_text('{"dependencies":{}}')
            row = {'name': ITEM['npm'], 'version': ITEM['version'], 'status': 'metadata-ok', 'bundled': True}
            with patch.object(target.host, 'running_hosts', return_value=[]), \
                 patch.object(target.market, 'fetch_catalog', return_value={'items': [ITEM]}), \
                 patch.object(target, 'choose_runtime', return_value=(Path('dsh.exe'), {'plugins': []})), \
                 patch.object(target.host, 'snapshot', return_value={'id': 'test-backup'}) as snapshot, \
                 patch.object(target, 'run_installer', return_value={}) as run, \
                 patch.object(target.host, 'probe', return_value={'runtime': '0.1.7-rc.2', 'plugins': [row]}):
                result = target.install_plugin.__wrapped__({'home': temp}, ITEM)
                self.assertEqual(result['status'], 'installed-not-verified')
                self.assertEqual(result['snapshot'], 'test-backup')
                self.assertEqual(result['functionality'], 'unverified')
                snapshot.assert_called_once()
                run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
