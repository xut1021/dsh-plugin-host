"""Hidden-widget checks; callbacks are fakes and never write DSH configuration."""
import copy
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ui


def plugin(name='dsh-example', **changes):
    data = {'name':name, 'version':'1.2.3', 'enabled':True, 'enabled_state':'enabled',
            'toggle_supported':True, 'status':'metadata-ok',
            'source':{'label':'本地', 'repository_url':'https://github.com/example/plugin'}}
    data.update(changes)
    return data


class PluginRowReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ui.ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.rows = ui.ctk.CTkFrame(self.root)
        self.count = ui.text(self.root)
        self.calls = []
        self.idle_callbacks = []
        self.runtime = {'plugins':[plugin()]}
        self.panel = SimpleNamespace(report={'present':True}, runtime_choices={'old':self.runtime},
            view_runtime=ui.tk.StringVar(master=self.root, value='old'), rows=self.rows,
            count_label=self.count, busy=False, actions=[],
            after_idle=self.idle_callbacks.append,
            show_source=lambda data:self.calls.append(('source',data)),
            toggle_plugin=lambda data,value:self.calls.append(('toggle',data,value.get())))

    def tearDown(self):
        self.rows.destroy()
        self.count.destroy()

    def render(self):
        ui.Panel.render_plugins(self.panel)

    def test_identical_refresh_reuses_widgets_and_does_no_configure_or_scroll_reset(self):
        self.render()
        row = self.panel.plugin_row_cache['dsh-example']
        controls = [self.count]+[row[key] for key in ('version','source','state','toggle','repository')]
        with patch.object(ui.ctk.CTkFrame, '__init__', side_effect=AssertionError('unexpected new row')):
            with patch.object(self.panel, 'after_idle', side_effect=AssertionError('unexpected scroll reset')):
                from contextlib import ExitStack
                with ExitStack() as stack:
                    for control in controls:
                        stack.enter_context(patch.object(control, 'configure', side_effect=AssertionError('unexpected redraw')))
                    self.runtime['plugins'] = copy.deepcopy(self.runtime['plugins'])
                    self.render()
        self.assertIs(row, self.panel.plugin_row_cache['dsh-example'])
        self.assertEqual(self.panel.actions, [row['toggle']])

    def test_latest_callbacks_pending_state_and_version_update_in_existing_row(self):
        self.render()
        row = self.panel.plugin_row_cache['dsh-example']
        new = plugin(version='2.0.0+patched', pending_enabled=False,
                     source={'label':'npm', 'repository_url':'https://gitlab.com/example/plugin'})
        self.runtime['plugins'] = [new]
        self.render()
        self.assertIs(row, self.panel.plugin_row_cache['dsh-example'])
        self.assertEqual(row['version'].cget('text'), '2.0.0 +补丁')
        self.assertFalse(row['value'].get())
        self.assertEqual(row['note'].cget('text'), '待重启')
        self.assertTrue(row['note_visible'])
        self.assertEqual(row['source'].cget('text'), 'npm')
        self.assertEqual(row['repository'].cget('text'), '项目仓库')
        row['source'].cget('command')()
        row['toggle'].cget('command')()
        self.assertIs(self.calls[0][1], new)
        self.assertEqual(self.calls[1], ('toggle',new,False))

    def test_busy_and_conditional_states_keep_action_registration_correct(self):
        self.render()
        row = self.panel.plugin_row_cache['dsh-example']
        self.panel.busy = True
        self.render()
        self.assertEqual(row['toggle'].cget('state'), 'disabled')
        self.assertIn(row['toggle'], self.panel.actions)
        self.runtime['plugins'] = [plugin(enabled=None, enabled_state='conditional', toggle_supported=False)]
        self.panel.busy = False
        self.render()
        self.assertEqual(row['toggle'].cget('state'), 'disabled')
        self.assertNotIn(row['toggle'], self.panel.actions)
        self.assertEqual(row['note'].cget('text'), '自动')
        self.runtime['plugins'] = [plugin(enabled=False)]
        self.render()
        self.assertEqual(row['toggle'].cget('state'), 'normal')
        self.assertFalse(row['value'].get())
        self.assertFalse(row['note_visible'])
        self.assertEqual(self.panel.actions, [row['toggle']])

    def test_removal_reorder_repository_disappearance_and_error_cleanup(self):
        self.runtime['plugins'] = [plugin('first'), plugin('second')]
        self.render()
        first, second = (self.panel.plugin_row_cache[key] for key in ('first','second'))
        self.runtime['plugins'] = [plugin('second', source={'label':'本地'})]
        self.render()
        self.assertFalse(first['row'].winfo_exists())
        self.assertNotIn(first['toggle'], self.panel.actions)
        self.assertEqual(second['grid_row'], 0)
        self.assertFalse(second['repository_visible'])
        self.runtime.update(error='检查失败', plugins=[])
        self.render()
        self.assertEqual(self.panel.plugin_row_cache, {})
        self.assertEqual(self.panel.actions, [])
        self.assertEqual(self.panel.plugin_error_label.cget('text'), '检查失败')
        self.runtime.pop('error')
        self.runtime['plugins'] = [plugin()]
        self.render()
        self.assertIsNone(self.panel.plugin_error_label)

    def test_32_row_refresh_timing_and_version_preview_reuse(self):
        self.runtime['plugins'] = [plugin('plugin-'+str(i)) for i in range(32)]
        started = time.perf_counter()
        self.render()
        initial = time.perf_counter()-started
        cached = dict(self.panel.plugin_row_cache)
        started = time.perf_counter()
        for _ in range(5):
            self.render()
        repeated = (time.perf_counter()-started)/5
        alternate = copy.deepcopy(self.runtime)
        for row in alternate['plugins']:
            row['status'] = 'version-blocked'
        self.panel.runtime_choices['new'] = alternate
        self.panel.view_runtime.set('new')
        started = time.perf_counter()
        self.render()
        switch = time.perf_counter()-started
        self.assertTrue(all(self.panel.plugin_row_cache[name] is row for name,row in cached.items()))
        self.assertEqual(len(self.panel.actions), 32)
        self.assertTrue(all(row['state'].cget('text') == '版本待适配' for row in cached.values()))
        print(f'\nPlugin rows: initial={initial:.4f}s unchanged={repeated:.4f}s changed-version={switch:.4f}s', flush=True)


if __name__ == '__main__':
    unittest.main()
