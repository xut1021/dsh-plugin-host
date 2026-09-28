"""Real hidden Tk widgets, fixture data only; no DSH or network operations."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import ui


def fixture_catalog():
    items = []
    for index in range(20):
        github_only = index in (2, 13)
        items.append({'name': f'Fixture Plugin {index:02d}', 'owner': f'author-{index}',
            'npm': '' if github_only else f'dsh-fixture-{index:02d}',
            'version': '' if github_only else '1.0.0',
            'url': f'https://github.com/example/fixture-{index:02d}',
            'description': f'插件 {index:02d} 的独立测试简介。 Searchable fixture description.',
            'categories': ['tools' if index % 2 else 'ui'],
            'stars': None if index in (1, 12) else 0 if index in (0, 13) else 1234,
            'installable': not github_only})
    return {'items': items, 'categories': {'ui': '界面', 'tools': '工具'},
            'updated': '2026-09-29', 'source': 'fixture'}


class MarketWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host_guard = patch.object(ui, 'host')
        cls.network_guard = patch.object(ui.market, 'fetch_catalog',
                                       side_effect=AssertionError('Fixture tests must not fetch the catalog'))
        cls.host_mock = cls.host_guard.start()
        cls.network_mock = cls.network_guard.start()
        cls.addClassCleanup(cls.host_guard.stop)
        cls.addClassCleanup(cls.network_guard.stop)
        cls.panel = ui.Panel(check_on_start=False)
        cls.panel.withdraw()
        cls.addClassCleanup(cls.destroy_panel)
        cls.panel.plugin_page.grid_remove()
        cls.panel.market_page.grid(row=1, column=0, sticky='nsew')

    @classmethod
    def destroy_panel(cls):
        # Cancel app and CTk timers before destroying their Tcl commands.
        for token in cls.panel.tk.call('after', 'info'):
            cls.panel.after_cancel(token)
        cls.panel.destroy()

    def setUp(self):
        self.panel.busy = False
        self.panel.market_catalog = fixture_catalog()
        self.panel.report = {'runtimes': [{'plugins': [
            {'name': 'dsh-fixture-01'}, {'name': 'dsh-fixture-12'}]}]}
        self.panel.market_category.configure(values=['全部分类', '界面', '工具'])
        self.panel.market_category.set('全部分类')
        self.set_query('')
        self.panel.market_page_index = 0
        self.panel.open_market_item = Mock()
        self.render(reset=True)

    def tearDown(self):
        self.assertEqual(self.host_mock.mock_calls, [], 'UI test attempted a host operation')
        self.network_mock.assert_not_called()
        self.assertEqual(self.panel.state(), 'withdrawn')

    def set_query(self, value):
        self.panel.market_search.delete(0, 'end')
        self.panel.market_search.insert(0, value)

    def render(self, reset=False):
        self.panel.render_market(reset=reset)
        self.panel.update_idletasks()
        self.panel.resize_market_cards()
        self.panel.update_idletasks()

    def visible_cards(self):
        return [card for card in self.panel.market_cards if card['row'].winfo_manager() == 'grid']

    def test_paging_and_search_keep_the_same_twelve_cards(self):
        original = [id(card['row']) for card in self.panel.market_cards]
        self.assertEqual(len(original), 12)
        self.panel.market_page_index = 1
        self.render()
        self.assertEqual(len(self.visible_cards()), 8)
        self.assertEqual([id(card['row']) for card in self.panel.market_cards], original)
        self.assertEqual(self.panel.market_page_label.cget('text'), '2 / 2')
        self.set_query('Fixture Plugin 13')
        self.render(reset=True)
        self.assertEqual(len(self.visible_cards()), 1)
        self.assertEqual(self.panel.market_cards[0]['item']['name'], 'Fixture Plugin 13')
        self.assertEqual([id(card['row']) for card in self.panel.market_cards], original)
        self.set_query('')
        self.render(reset=True)
        self.assertEqual(len(self.visible_cards()), 12)

    def test_zero_unknown_and_exact_stars_survive_reuse(self):
        cards = self.panel.market_cards
        self.assertEqual(cards[0]['stars'].cget('text'), '☆  0 Stars')
        self.assertEqual(cards[1]['stars'].cget('text'), '☆  Stars 暂无数据')
        self.assertEqual(cards[2]['stars'].cget('text'), '☆  1,234 Stars')
        self.panel.market_page_index = 1
        self.render()
        self.assertEqual(cards[0]['stars'].cget('text'), '☆  Stars 暂无数据')
        self.assertEqual(cards[1]['stars'].cget('text'), '☆  0 Stars')

    def test_install_installed_details_and_busy_states_survive_reuse(self):
        def states():
            return [(card['action'].cget('text'), card['action'].cget('state'))
                    for card in self.panel.market_cards[:3]]
        self.assertEqual(states(), [('安装', 'normal'), ('✓ 已安装', 'disabled'), ('详情', 'normal')])
        self.panel.market_page_index = 1
        self.render()
        self.assertEqual(states(), [('✓ 已安装', 'disabled'), ('详情', 'normal'), ('安装', 'normal')])
        self.panel.busy = True
        self.render()
        self.assertTrue(all(state == 'disabled' for _, state in states()))
        self.panel.busy = False
        self.panel.market_page_index = 0
        self.render()
        self.assertEqual(states(), [('安装', 'normal'), ('✓ 已安装', 'disabled'), ('详情', 'normal')])

    def test_reused_button_invokes_the_current_item(self):
        action = self.panel.market_cards[0]['action']
        action.invoke()
        self.assertEqual(self.panel.open_market_item.call_args.args[0]['name'], 'Fixture Plugin 00')
        self.set_query('Fixture Plugin 14')
        self.render(reset=True)
        self.assertIs(self.panel.market_cards[0]['action'], action)
        action.invoke()
        self.assertIs(self.panel.open_market_item.call_args.args[0], self.panel.market_catalog['items'][14])

    def test_actions_do_not_accumulate_old_or_duplicate_buttons(self):
        baseline = len(self.panel.actions)
        for page in (1, 0, 1, 0):
            self.panel.market_page_index = page
            self.render()
            self.assertLessEqual(len(self.panel.actions), baseline)
            self.assertEqual(len(self.panel.actions), len(set(self.panel.actions)))
            self.assertTrue(all(widget.winfo_exists() for widget in self.panel.actions))
            active = set(self.panel.actions)
            for card in self.visible_cards():
                self.assertEqual(card['action'] in active, card['action'].cget('state') != 'disabled')

    def test_empty_results_and_category_can_restore_the_pool(self):
        original = [id(card['row']) for card in self.panel.market_cards]
        self.set_query('no-fixture-matches-this')
        self.render(reset=True)
        self.assertEqual(self.visible_cards(), [])
        self.assertEqual(self.panel.market_empty.winfo_manager(), 'grid')
        self.assertEqual(self.panel.market_next.cget('state'), 'disabled')
        self.set_query('')
        self.panel.market_category.set('工具')
        self.render(reset=True)
        self.assertEqual(len(self.visible_cards()), 10)
        self.assertTrue(all('tools' in card['item']['categories'] for card in self.visible_cards()))
        self.assertEqual(self.panel.market_empty.winfo_manager(), '')
        self.assertEqual([id(card['row']) for card in self.panel.market_cards], original)

    def test_unchanged_query_keys_do_not_schedule_another_search(self):
        self.set_query('Fixture')
        self.render(reset=True)
        event = tk.Event()
        with patch.object(self.panel, 'after', wraps=self.panel.after) as after:
            for key in ('Left', 'Right', 'Shift_L'):
                event.keysym = key
                self.panel.schedule_search(event)
            after.assert_not_called()
        self.assertIsNone(self.panel.search_timer)
        self.set_query('Fixture Plugin 14')
        self.panel.schedule_search(event)
        self.assertIsNotNone(self.panel.search_timer)
        self.render(reset=True)
        self.assertIsNone(self.panel.search_timer)


if __name__ == '__main__':
    unittest.main()
