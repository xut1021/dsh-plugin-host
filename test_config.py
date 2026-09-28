"""First-run validation without installing shortcuts or launching DSH."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import host


class ConfigurationValidation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dsh-config-test-')
        self.root=Path(self.temp.name)
        self.root_patch=patch.object(host,'ROOT',self.root)
        self.root_patch.start()
        self.config={'home':str(self.root/'home'),
            'current_exe':str(self.root/'current'/'DeepSeek Harness.exe'),
            'fallback_exe':str(self.root/'fallback'/'DeepSeek Harness.exe'),
            'launch_env':{}}

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def save(self,config=None,encoding='utf-8'):
        (self.root/'local.json').write_text(json.dumps(config or self.config),encoding=encoding)

    def installation_fixture(self):
        profile=Path(self.config['home'])/'profiles/desktop'
        profile.mkdir(parents=True)
        (profile/'package.json').write_text('{}')
        for key in ('current_exe','fallback_exe'):
            exe=Path(self.config[key])
            (exe.parent/'resources').mkdir(parents=True)
            exe.write_bytes(b'fixture, never executed')
            (exe.parent/'resources/app.asar').write_bytes(b'fixture, never opened')

    def test_missing_configuration_explains_manual_setup(self):
        with self.assertRaisesRegex(RuntimeError,'local.example.json'):
            host.load_config()

    def test_malformed_configuration_does_not_echo_contents(self):
        (self.root/'local.json').write_text('{not-json: confidential-value}',encoding='utf-8')
        with self.assertRaises(RuntimeError) as caught:host.load_config()
        self.assertIn('JSON',str(caught.exception))
        self.assertNotIn('confidential-value',str(caught.exception))

    def test_structure_requires_absolute_paths_and_string_environment(self):
        for change in ({'home':'relative/home'},{'current_exe':None},{'launch_env':{'HTTP_PROXY':5}},
                       {'launch_env':{'DSH_HOME':str(self.root/'other-home')}}):
            with self.subTest(change=change):
                self.save({**self.config,**change})
                with self.assertRaises(RuntimeError):host.load_config()

    def test_utf8_bom_and_unset_preference_are_accepted(self):
        self.save({**self.config,'preferred_exe':None},encoding='utf-8-sig')
        loaded=host.load_config()
        self.assertEqual(loaded['home'],self.config['home'])
        self.assertNotIn('preferred_exe',loaded)

    def test_installation_preflight_checks_profile_and_complete_runtimes(self):
        self.save()
        with self.assertRaisesRegex(RuntimeError,'profiles/desktop/package.json'):
            host.load_config(check_paths=True)
        self.installation_fixture()
        self.assertEqual(host.load_config(check_paths=True),self.config)
        (Path(self.config['fallback_exe']).parent/'resources/app.asar').unlink()
        with self.assertRaisesRegex(RuntimeError,'fallback_exe.*resources/app.asar'):
            host.load_config(check_paths=True)

    def test_powershell_can_resolve_from_path_or_program_files(self):
        binary=self.root/'custom-pwsh.exe'
        binary.write_bytes(b'fixture, never executed')
        with patch.object(host.shutil,'which',side_effect=lambda name:str(binary) if name=='pwsh.exe' else None):
            self.assertEqual(host.powershell_executable(),str(binary))
        installed=self.root/'PowerShell/7/pwsh.exe'
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b'fixture, never executed')
        with patch.object(host.shutil,'which',return_value=None),patch.dict(os.environ,{'ProgramFiles':str(self.root)}):
            self.assertEqual(host.powershell_executable(),str(installed))
            installed.unlink()
            with self.assertRaisesRegex(RuntimeError,'PowerShell 7'):
                host.powershell_executable()


if __name__=='__main__':unittest.main(verbosity=2)
