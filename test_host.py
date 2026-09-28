"""Isolated Windows tests; optional loader tests require DSH_TEST_RUNTIME explicitly."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import host

@unittest.skipUnless(os.name=='nt','Encrypted profile backups require Windows DPAPI')
class ProfileSafety(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='host-test-')
        self.root=Path(self.temp.name).resolve()
        self.cfg={'home':str(self.root/'home')}
        self.profile=Path(self.cfg['home'])/'profiles/desktop'
        self.profile.mkdir(parents=True)
        (self.profile/'package.json').write_text('{"dependencies":{}}')
        (self.profile/'cordis.patch.yml').write_text('- id: example\n  config:\n    choice: original\n')
        self.state_patch=patch.object(host,'STATE',self.root/'state')
        self.state_patch.start()
        self.running_patch=patch.object(host,'running_hosts',return_value=[])
        self.running_patch.start()
    def tearDown(self):
        self.running_patch.stop();self.state_patch.stop();self.temp.cleanup()
    def test_encrypted_roundtrip_and_restore(self):
        original=host.profile_hashes(self.profile)
        meta=host.snapshot(self.cfg)
        encrypted=(host.STATE/'snapshots'/meta['id']/'profile.dpapi').read_bytes()
        self.assertNotIn(b'choice: original',encrypted)
        (self.profile/'cordis.patch.yml').write_text('- id: example\n  disabled: true\n')
        host._save_pending_plugins(self.cfg,{'example':False})
        result=host.restore(self.cfg,meta['id'])
        self.assertEqual(original,host.profile_hashes(self.profile))
        self.assertEqual(result['canceled_pending_plugins'],1)
        self.assertEqual(host.pending_plugin_changes(self.cfg),{})
    def test_corrupt_backup_and_active_instance_do_not_write(self):
        meta=host.snapshot(self.cfg)
        path=host.STATE/'snapshots'/meta['id']/'profile.dpapi'
        path.write_bytes(path.read_bytes()+b'corruption')
        before=host.profile_hashes(self.profile)
        host._save_pending_plugins(self.cfg,{'example':False})
        with self.assertRaisesRegex(RuntimeError,'integrity'):
            host.restore(self.cfg,meta['id'])
        with patch.object(host,'running_hosts',return_value=[{'pid':1}]):
            with self.assertRaises(RuntimeError):host.restore(self.cfg,meta['id'])
        self.assertEqual(before,host.profile_hashes(self.profile))
        self.assertEqual(host.pending_plugin_changes(self.cfg),{'example':False})
    def test_mid_restore_failure_rolls_back_current_state(self):
        meta=host.snapshot(self.cfg)
        (self.profile/'package.json').write_text('{"dependencies":{},"name":"current"}')
        (self.profile/'cordis.patch.yml').write_text('- id: example\n  disabled: true\n')
        before=host.profile_hashes(self.profile)
        host._save_pending_plugins(self.cfg,{'example':True})
        replace=os.replace
        def fail(src,dst):
            if Path(dst)==self.profile/'cordis.patch.yml':raise OSError('injected failure')
            return replace(src,dst)
        with patch.object(host.os,'replace',side_effect=fail):
            with self.assertRaisesRegex(OSError,'injected'):
                host.restore(self.cfg,meta['id'])
        self.assertEqual(before,host.profile_hashes(self.profile))
        self.assertEqual(host.pending_plugin_changes(self.cfg),{'example':True})
    def test_plugin_drift_rejects_configuration_only_restore(self):
        meta=host.snapshot(self.cfg)
        (self.profile/'package.json').write_text('{"dependencies":{"new-plugin":"1.0.0"}}')
        before=host.profile_hashes(self.profile)
        with self.assertRaisesRegex(RuntimeError,'插件安装版本'):
            host.restore(self.cfg,meta['id'])
        self.assertEqual(before,host.profile_hashes(self.profile))
    def test_pending_clear_failure_rolls_back_restore_and_retains_queue(self):
        meta=host.snapshot(self.cfg)
        (self.profile/'cordis.patch.yml').write_text('- id: example\n  disabled: true\n')
        before=host.profile_hashes(self.profile)
        host._save_pending_plugins(self.cfg,{'example':False})
        with patch.object(host,'_save_pending_plugins',side_effect=OSError('injected queue write failure')):
            with self.assertRaisesRegex(OSError,'queue write failure'):
                host.restore(self.cfg,meta['id'])
        self.assertEqual(before,host.profile_hashes(self.profile))
        self.assertEqual(host.pending_plugin_changes(self.cfg),{'example':False})

@unittest.skipUnless(os.name=='nt','Version selection uses the Windows profile mutex')
class VersionSelection(unittest.TestCase):
    """No real DSH process or installation is changed by version switching tests."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='version-test-')
        self.root=Path(self.temp.name).resolve()
        self.cfg={'home':str(self.root/'home'),
            'current_exe':str(self.root/'current'/'DeepSeek Harness.exe'),
            'fallback_exe':str(self.root/'fallback'/'DeepSeek Harness.exe')}
        self.blocked=set()
        self.errors=set()
        self.patches=[patch.object(host,'ROOT',self.root),patch.object(host,'STATE',self.root/'state'),
            patch.object(host,'running_hosts',return_value=[]),patch.object(host,'probe',side_effect=self.probe),
            patch.object(host,'snapshot',return_value={'id':'test-snapshot'}),patch.object(host.subprocess,'Popen')]
        self.mocks=[p.start() for p in self.patches]
        self.running,self.inspect,self.backup,self.start=self.mocks[2:]
        host.write_json(self.root/'local.json',self.cfg)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def probe(self,exe,profile):
        if exe in self.errors:raise RuntimeError('mock runtime probe failed')
        return {'exe':exe,'runtime':'0.2.0' if exe==self.cfg['current_exe'] else '0.1.7',
            'plugins':[{'name':'example','version':'1.0.0','enabled':True,
                'status':'version-blocked' if exe in self.blocked else 'metadata-ok'}]}
    def active(self,exe,profile=None):
        return {'pid':123,'exe':exe,'profile':profile or str(Path(self.cfg['home'])/'profiles/desktop')}
    def test_blocked_or_probe_error_does_not_save_preference(self):
        original=(self.root/'local.json').read_bytes()
        for failure in (self.blocked,self.errors):
            with self.subTest(failure=failure):
                failure.add(self.cfg['current_exe'])
                with self.assertRaisesRegex(RuntimeError,'默认版本未改动'):
                    host.switch_version(self.cfg,self.cfg['current_exe'])
                self.assertEqual(original,(self.root/'local.json').read_bytes())
                failure.clear()
        self.start.assert_not_called();self.backup.assert_not_called()
    def test_eligible_choice_is_saved_and_honored_on_next_launch(self):
        chosen=self.cfg['fallback_exe']
        result=host.switch_version(self.cfg,chosen)
        self.assertEqual(result['status'],'started-not-verified')
        self.assertEqual(host.load_config()['preferred_exe'],chosen)
        self.assertEqual(self.start.call_args.args[0][0],chosen)
        self.start.reset_mock()
        result=host.smart_launch(host.load_config())
        self.assertEqual(result['launched'],chosen)
        self.assertEqual(self.start.call_args.args[0][0],chosen)
    def test_other_running_host_is_left_alone_and_choice_saved(self):
        for profile in (None,str(self.root/'other-profile')):
            with self.subTest(profile=profile):
                self.running.return_value=[self.active(self.cfg['current_exe'],profile)]
                result=host.switch_version(self.cfg,self.cfg['fallback_exe'])
                self.assertEqual(result['status'],'needs-exit')
                self.assertEqual(result['selected'],self.cfg['fallback_exe'])
                self.assertEqual(host.load_config()['preferred_exe'],self.cfg['fallback_exe'])
        self.start.assert_not_called();self.backup.assert_not_called()
    def test_same_running_version_is_reused_without_start(self):
        self.running.return_value=[self.active(self.cfg['fallback_exe'])]
        result=host.switch_version(self.cfg,self.cfg['fallback_exe'])
        self.assertEqual(result['status'],'reused')
        self.start.assert_not_called();self.backup.assert_not_called()
    def test_launch_failure_does_not_claim_success(self):
        self.start.side_effect=OSError('mock start failed')
        with self.assertRaisesRegex(RuntimeError,'默认版本已保存，但启动未完成'):
            host.switch_version(self.cfg,self.cfg['fallback_exe'])
        self.assertEqual(host.load_config()['preferred_exe'],self.cfg['fallback_exe'])
        self.assertFalse((host.STATE/'last-launch.json').exists())
    def test_ineligible_preference_falls_back_without_rewriting_choice(self):
        self.cfg['preferred_exe']=self.cfg['current_exe']
        self.blocked.add(self.cfg['current_exe'])
        host.write_json(self.root/'local.json',self.cfg)
        result=host.smart_launch(self.cfg)
        self.assertEqual(result['launched'],self.cfg['fallback_exe'])
        self.assertEqual(host.load_config()['preferred_exe'],self.cfg['current_exe'])
    def test_smart_launch_waits_for_other_managed_version_to_exit(self):
        self.cfg['preferred_exe']=self.cfg['fallback_exe']
        self.running.return_value=[self.active(self.cfg['current_exe'])]
        result=host.smart_launch(self.cfg)
        self.assertEqual(result['status'],'needs-exit')
        self.assertEqual(result['selected'],self.cfg['fallback_exe'])
        self.start.assert_not_called();self.backup.assert_not_called()
    def test_smart_launch_without_preference_preserves_existing_instance(self):
        self.running.return_value=[self.active(self.cfg['fallback_exe'])]
        self.errors.update((self.cfg['current_exe'],self.cfg['fallback_exe']))
        result=host.smart_launch(self.cfg)
        self.assertEqual(result['status'],'existing-managed-instance')
        self.inspect.assert_not_called()
        self.assertEqual(self.start.call_args.args[0][0],self.cfg['fallback_exe'])
    def test_stale_paths_refuse_write_and_other_settings_are_preserved(self):
        changed={**self.cfg,'note':'keep this'}
        host.write_json(self.root/'local.json',changed)
        self.running.return_value=[self.active(self.cfg['fallback_exe'])]
        host.switch_version(self.cfg,self.cfg['fallback_exe'])
        self.assertEqual(host.load_config()['note'],'keep this')
        changed['home']=str(self.root/'new-home')
        host.write_json(self.root/'local.json',changed)
        with self.assertRaisesRegex(RuntimeError,'托管路径或启动配置已变化'):
            host.switch_version(self.cfg,self.cfg['fallback_exe'])
        self.assertEqual(host.load_config(),changed)
    def test_probe_error_is_ineligible_and_keeps_other_runtime_available(self):
        self.errors.add(self.cfg['current_exe'])
        report=host.evaluate(self.cfg)
        current,fallback=report['runtimes']
        self.assertEqual(current['error'],'mock runtime probe failed')
        self.assertFalse(current['eligible_for_trial'])
        self.assertTrue(fallback['eligible_for_trial'])
        self.start.assert_not_called();self.backup.assert_not_called()
    def test_blocked_release_never_launches(self):
        self.blocked.add(self.cfg['current_exe'])
        original=(self.root/'local.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'启动前检查未通过'):
            host.launch(self.cfg,self.cfg['current_exe'])
        self.start.assert_not_called();self.backup.assert_not_called()
        self.assertEqual((self.root/'local.json').read_bytes(),original)

@unittest.skipUnless(os.name=='nt' and os.environ.get('DSH_TEST_RUNTIME'),
    'Optional loader tests need Windows and an explicit DSH_TEST_RUNTIME executable path')
class PluginToggles(unittest.TestCase):
    """Opt-in loader integration; only fabricated temporary profiles, no desktop boot."""
    @classmethod
    def setUpClass(cls):
        runtime=Path(os.environ['DSH_TEST_RUNTIME'])
        if not runtime.is_absolute() or not runtime.is_file():
            raise RuntimeError('DSH_TEST_RUNTIME must be an existing absolute executable path')
        if not (runtime.parent/'resources/app.asar').is_file():
            raise RuntimeError('DSH_TEST_RUNTIME needs a complete desktop installation with resources/app.asar')
        cls.runtime=str(runtime)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='plugin-toggle-test-')
        self.root=Path(self.temp.name).resolve()
        self.cfg={'home':str(self.root/'home'),'current_exe':self.runtime,'fallback_exe':self.runtime}
        self.profile=Path(self.cfg['home'])/'profiles/desktop'
        self.profile.mkdir(parents=True)
        host.write_json(self.profile/'package.json',{'name':'test-profile','dependencies':{'alpha':'1.0.0','beta':'1.0.0'},
            'dsh':{'profile':{'bundles':['alpha','beta']}}})
        for name in ('alpha','beta'):
            folder=self.profile/'node_modules'/name
            (folder/'lib').mkdir(parents=True)
            host.write_json(folder/'package.json',{'name':name,'version':'1.0.0','main':'lib/index.js',
                'dsh':{'bundle':{'patch':'cordis.patch.yml'},'client':{'inject':['alpha'] if name=='beta' else []}}})
            (folder/'lib/index.js').write_text('// Never imported by these tests.\n')
            (folder/'lib/client.js').write_text("// .provide('alphaService')\n" if name=='alpha' else "// inject: ['alphaService']\n")
            (folder/'cordis.patch.yml').write_text('- insert:\n  - id: '+name+'\n    name: '+name+'\n',encoding='utf-8')
        self.patch=self.profile/'cordis.patch.yml'
        self.original=('# Keep this header\n- id: alpha\n  disabled: false # Keep this switch comment\n'
            '  config:\n    label: "unchanged string"\n    expression: !!js "false"\n'
            '- id: beta\n  disabled: true # Keep beta comment\n# Keep the final comment\n').encode()
        self.patch.write_bytes(self.original)
        self.state_patch=patch.object(host,'STATE',self.root/'state');self.state_patch.start()
        self.running_patch=patch.object(host,'running_hosts',return_value=[])
        self.running=self.running_patch.start()
    def tearDown(self):
        self.running_patch.stop();self.state_patch.stop();self.temp.cleanup()
    def active(self):
        self.running.return_value=[{'pid':1,'exe':self.runtime,'profile':str(self.profile)}]
    def test_apply_disabled_flag_preserves_all_other_bytes_and_verifies_loader(self):
        result=host.set_plugin_enabled(self.cfg,'alpha',False)
        self.assertEqual(result['status'],'applied')
        self.assertEqual(self.patch.read_bytes(),self.original.replace(b'disabled: false',b'disabled: true'))
        self.assertTrue((host.STATE/'snapshots'/result['snapshot']/'profile.dpapi').exists())
        report=host.probe(self.runtime,self.profile)
        self.assertFalse(next(p for p in report['plugins'] if p['name']=='alpha')['enabled'])
        result=host.set_plugin_enabled(self.cfg,'alpha',True)
        self.assertEqual(self.patch.read_bytes(),self.original)
    def test_running_queue_does_not_change_profile_and_revert_removes_request(self):
        self.active()
        result=host.set_plugin_enabled(self.cfg,'alpha',False)
        self.assertEqual(result['status'],'queued');self.assertTrue(result['restart_required'])
        self.assertEqual(self.patch.read_bytes(),self.original)
        report=host.evaluate(self.cfg)
        plugin=next(p for p in report['runtimes'][0]['plugins'] if p['name']=='alpha')
        self.assertFalse(plugin['pending_enabled']);self.assertTrue(plugin['enabled'])
        result=host.set_plugin_enabled(self.cfg,'alpha',True)
        self.assertEqual(result['status'],'unchanged')
        self.assertEqual(host.pending_plugin_changes(self.cfg),{})
        self.assertEqual(self.patch.read_bytes(),self.original)
    def test_pending_is_applied_before_smart_launch_and_cleared(self):
        self.active();host.set_plugin_enabled(self.cfg,'alpha',False)
        self.running.return_value=[]
        def fake_launch(config,exe):
            self.assertEqual(host.pending_plugin_changes(config),{})
            self.assertEqual(self.patch.read_bytes(),self.original.replace(b'disabled: false',b'disabled: true'))
            return {'status':'started-not-verified'}
        with patch.object(host,'launch',side_effect=fake_launch) as start:
            result=host.smart_launch(self.cfg)
        self.assertEqual(result['status'],'started-not-verified');start.assert_called_once()
        self.assertEqual(host.pending_plugin_changes(self.cfg),{})
        self.assertEqual(self.patch.read_bytes(),self.original.replace(b'disabled: false',b'disabled: true'))
    def test_enable_refuses_disabled_or_missing_dependency_and_incompatible_version(self):
        host.set_plugin_enabled(self.cfg,'alpha',False)
        before=self.patch.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'依赖未启用或不兼容'):
            host.set_plugin_enabled(self.cfg,'beta',True)
        meta_path=self.profile/'node_modules/beta/package.json'
        meta=json.loads(meta_path.read_text());meta['dsh']['client']['inject']=['missing-provider']
        host.write_json(meta_path,meta)
        with self.assertRaisesRegex(RuntimeError,'missing-provider'):
            host.set_plugin_enabled(self.cfg,'beta',True)
        meta['peerDependencies']={'@deepseek-ai/dsh':'^99.0.0'};host.write_json(meta_path,meta)
        with self.assertRaisesRegex(RuntimeError,'未通过声明检查'):
            host.set_plugin_enabled(self.cfg,'beta',True)
        self.assertEqual(self.patch.read_bytes(),before)
    def test_failed_verification_rolls_back_and_keeps_pending(self):
        self.active();host.set_plugin_enabled(self.cfg,'alpha',False)
        self.running.return_value=[]
        actual=host.probe
        calls=0
        def fail_after_write(exe,profile):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('injected post-write verification failure')
            return actual(exe,profile)
        with patch.object(host,'probe',side_effect=fail_after_write):
            with self.assertRaisesRegex(RuntimeError,'injected post-write'):
                host.apply_pending_plugins(self.cfg)
        self.assertEqual(self.patch.read_bytes(),self.original)
        self.assertEqual(host.pending_plugin_changes(self.cfg),{'alpha':False})
    def test_queue_cannot_disable_dependency_of_pending_enabled_plugin(self):
        self.active();host.set_plugin_enabled(self.cfg,'beta',True)
        with self.assertRaisesRegex(RuntimeError,'依赖未启用或不兼容'):
            host.set_plugin_enabled(self.cfg,'alpha',False)
        self.assertEqual(host.pending_plugin_changes(self.cfg),{'beta':True})
        self.assertEqual(self.patch.read_bytes(),self.original)
    def test_stopped_direct_toggle_preserves_and_applies_other_pending_choices(self):
        self.active();host.set_plugin_enabled(self.cfg,'beta',True)
        self.running.return_value=[]
        result=host.set_plugin_enabled(self.cfg,'alpha',True)
        self.assertEqual(result['plugins'],{'beta':True})
        self.assertEqual(host.pending_plugin_changes(self.cfg),{})
        checked=host.probe(self.runtime,self.profile)
        self.assertTrue(all(p['enabled'] for p in checked['plugins']))
    def test_missing_flag_is_appended_without_rewriting_comments_or_settings(self):
        self.patch.write_bytes(self.original.replace(b'  disabled: false # Keep this switch comment\n',b'  # Keep this switch comment\n'))
        before=self.patch.read_bytes()
        host.set_plugin_enabled(self.cfg,'alpha',False)
        changed=self.patch.read_bytes()
        self.assertIn(b'  # Keep this switch comment\n',changed)
        self.assertIn(b'    expression: !!js "false"\n',changed)
        self.assertIn(b'# Keep the final comment\n',changed)
        self.assertEqual(changed.count(b'disabled: true'),2)
        self.assertGreater(len(changed),len(before))
    def test_empty_flow_patch_and_multiple_pending_flags(self):
        self.patch.write_text('# Empty flow document\n[] # End comment\n',encoding='utf-8')
        self.active()
        host.set_plugin_enabled(self.cfg,'beta',False)
        host.set_plugin_enabled(self.cfg,'alpha',False)
        self.assertEqual(host.pending_plugin_changes(self.cfg),{'beta':False,'alpha':False})
        self.running.return_value=[]
        result=host.apply_pending_plugins(self.cfg)
        self.assertEqual(result['status'],'applied')
        changed=self.patch.read_text(encoding='utf-8')
        self.assertTrue(changed.startswith('# Empty flow document\n['))
        self.assertIn('] # End comment',changed)
        self.assertEqual(changed.count('disabled: true'),2)
        self.assertEqual(len(list((host.STATE/'snapshots').glob('*/snapshot.json'))),1)
        self.assertEqual(host.pending_plugin_changes(self.cfg),{})

if __name__=='__main__':unittest.main(verbosity=2)
