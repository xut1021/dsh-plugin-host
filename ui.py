"""Local DSH control panel; host.py owns version and configuration operations."""
import ctypes
from ctypes import wintypes
import datetime as dt
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from urllib.parse import urlsplit
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
import customtkinter as ctk
import host
import market
from ui_text import fit_text, wrap_preview

C = dict(bg='#F7F9F8', white='#FFFFFF', ink='#202B28', muted='#697772',
         accent='#147D64', hover='#106650', line='#E4EAE7', soft='#EAF5EF',
         navy='#273C35', green='#147D64', green_bg='#EAF5EF',
         amber='#98631F', amber_bg='#FFF6E8', faint='#F5F8F6')
FONT = 'Microsoft YaHei UI'
ctk.set_appearance_mode('light')
ctk.set_default_color_theme('blue')


def same_path(a, b):
    return bool(a and b) and os.path.normcase(str(a)) == os.path.normcase(str(b))


def text(parent, value='', size=13, color=None, bold=False, **kw):
    return ctk.CTkLabel(parent, text=value, font=(FONT, size, 'bold' if bold else 'normal'),
                        text_color=color or C['ink'], anchor=kw.pop('anchor', 'w'), **kw)


def button(parent, value, command, primary=False, **kw):
    return ctk.CTkButton(parent, text=value, command=command, height=38,
                        corner_radius=8, font=(FONT, 13),
                        fg_color=C['accent'] if primary else C['soft'],
                        hover_color=C['hover'] if primary else '#DBEBE2',
                        text_color='white' if primary else C['accent'], **kw)


def badge(parent, value, color, bg):
    return text(parent, value, size=11, color=color, fg_color=bg,
                corner_radius=6, padx=10, height=26)


def display_name(name):
    slug = name.split('/')[-1]
    for prefix in ('dsh-plugin-', 'dsh-'):
        if slug.startswith(prefix):
            slug = slug[len(prefix):]
            break
    return slug.replace('-', ' ').replace('_', ' ').title()


class Tabs(ctk.CTkFrame):
    def __init__(self, parent, values, command):
        super().__init__(parent, fg_color='transparent')
        self.command = command
        self.selected = values[0]
        self.buttons = {}
        for column, value in enumerate(values):
            tab = ctk.CTkButton(self, text=value, width=108, height=42, corner_radius=0,
                fg_color='transparent', hover_color=C['faint'], text_color=C['muted'],
                font=(FONT, 15), command=lambda v=value: self.choose(v))
            tab.grid(row=0, column=column, padx=(0, 12))
            line = ctk.CTkFrame(self, width=1, height=3, corner_radius=0, fg_color='white')
            line.grid(row=1, column=column, sticky='ew', padx=(12, 24))
            self.buttons[value] = (tab, line)
        self.set(self.selected)

    def get(self):
        return self.selected

    def set(self, value):
        self.selected = value
        for name, (tab, line) in self.buttons.items():
            tab.configure(text_color=C['accent'] if name == value else C['muted'],
                          font=(FONT, 15, 'bold' if name == value else 'normal'))
            line.configure(fg_color=C['accent'] if name == value else 'white')

    def choose(self, value):
        self.set(value)
        self.command(value)


class Panel(ctk.CTk):
    def __init__(self, check_on_start=True):
        super().__init__()
        self.title('DSH 插件托管')
        self.geometry('1240x900')
        self.minsize(1040, 760)
        self.configure(fg_color=C['bg'])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.report = None
        self.busy = False
        self.refresh_after_error = False
        self.jobs = queue.Queue()
        self.actions = []
        self.version_dialog = None
        self.market_dialog = None
        self.market_catalog = None
        self.market_page_index = 0
        self.market_card_labels = []
        self.market_title_font = ctk.CTkFont(family=FONT, size=17, weight='bold')
        self.market_body_font = ctk.CTkFont(family=FONT, size=13)
        self.market_card_width = None
        self.market_cards = []
        self.market_resize_timer = None
        self.market_index_catalog = None
        self.market_filter_key = None
        self.market_last_query = ''
        self.search_timer = None
        self.view_runtime = tk.StringVar(value='正在检查…')
        self.status = tk.StringVar(value='正在读取本机状态…')
        self.snapshot_ids = {}
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.build_header()
        self.build_runtime()
        self.build_notice()
        self.build_content()
        self.build_footer()
        self.after(80, self.poll)
        if check_on_start:
            self.after(120, self.check)

    def action(self, parent, value, command, primary=False, **kw):
        widget = button(parent, value, command, primary, **kw)
        self.actions.append(widget)
        return widget

    def build_header(self):
        bar = ctk.CTkFrame(self, fg_color='transparent')
        bar.grid(row=0, column=0, sticky='ew', padx=32, pady=(22, 18))
        mark = text(bar, 'D', size=25, color='white', bold=True, width=43, height=43,
                    fg_color=C['accent'], corner_radius=12, anchor='center')
        mark.pack(side='left', padx=(0, 13))
        brand = ctk.CTkFrame(bar, fg_color='transparent')
        brand.pack(side='left')
        text(brand, '插件托管', size=24, bold=True, height=30).pack(anchor='w')
        text(brand, 'DeepSeek Harness 的插件与设置', size=12, color=C['muted'], height=20).pack(anchor='w')
        self.action(bar, '打开 DSH', self.open_dsh, primary=True, width=116).pack(side='right')
        self.action(bar, '刷新检查', self.check, width=104).pack(side='right', padx=(0, 10))

    def build_runtime(self):
        card = ctk.CTkFrame(self, fg_color='white', corner_radius=12, border_width=1, border_color=C['line'])
        card.grid(row=1, column=0, sticky='ew', padx=32)
        card.grid_columnconfigure(1, weight=1)
        left = ctk.CTkFrame(card, fg_color='transparent')
        left.grid(row=0, column=0, sticky='w', padx=20, pady=14)
        text(left, '当前运行', color=C['muted'], size=12).pack(side='left', padx=(0, 12))
        self.current_version = text(left, '读取中…', size=20, bold=True, height=35)
        self.current_version.pack(side='left')
        self.running_badge = badge(left, '读取中', C['muted'], C['faint'])
        self.running_badge.pack(side='left', padx=(12, 0))
        self.default_label = text(card, '插件与设置沿用同一份配置', color=C['muted'], size=12)
        self.default_label.grid(row=0, column=1, sticky='e', padx=14)
        right = ctk.CTkFrame(card, fg_color='transparent')
        right.grid(row=0, column=2, padx=(0, 16), pady=10)
        self.switch_button = self.action(right, '切换版本  ⇄', self.open_versions, width=118)
        self.switch_button.pack()
        self.version_count = text(right, '', color=C['muted'], size=11, anchor='center')

    def build_notice(self):
        self.notice = ctk.CTkFrame(self, fg_color=C['amber_bg'], corner_radius=10)
        self.notice.grid(row=2, column=0, sticky='ew', padx=32, pady=(12, 0))
        self.notice.grid_columnconfigure(0, weight=1)
        self.notice_text = text(self.notice, '正在检查更新后的插件兼容情况…', color=C['amber'],
                                size=12, wraplength=720, justify='left')
        self.notice_text.grid(row=0, column=0, sticky='w', padx=16, pady=10)
        self.notice_button = self.action(self.notice, '查看版本', self.open_versions, width=92)
        self.notice_button.configure(fg_color=C['amber_bg'], hover_color='#F8E8CE', text_color=C['amber'])
        self.notice_button.grid(row=0, column=1, padx=(8, 8), pady=3)

    def build_content(self):
        self.content = ctk.CTkFrame(self, fg_color=C['white'], corner_radius=14,
                                    border_width=1, border_color=C['line'])
        self.content.grid(row=3, column=0, sticky='nsew', padx=32, pady=(16, 0))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(self.content, fg_color='transparent')
        toolbar.grid(row=0, column=0, sticky='ew', padx=20, pady=(8, 16))
        self.tabs = Tabs(toolbar, ['插件清单', '插件市场', '配置备份'], self.change_tab)
        self.tabs.set('插件清单')
        self.tabs.pack(side='left')
        self.count_label = text(toolbar, '', color=C['muted'], size=12)
        self.count_label.pack(side='left', padx=14)
        self.runtime_menu = ctk.CTkOptionMenu(toolbar, values=['正在检查…'], variable=self.view_runtime,
            command=lambda _: self.render_plugins(), width=225, height=34,
            fg_color=C['faint'], button_color=C['faint'], button_hover_color=C['line'],
            text_color=C['muted'], font=(FONT, 12), dropdown_font=(FONT, 12),
            dropdown_fg_color='white', dropdown_text_color=C['ink'], dynamic_resizing=False)
        self.runtime_menu.pack(side='right')
        self.plugin_page = ctk.CTkFrame(self.content, fg_color='transparent')
        self.plugin_page.grid(row=1, column=0, sticky='nsew', padx=18, pady=(0, 14))
        self.plugin_page.grid_columnconfigure(0, weight=1)
        self.plugin_page.grid_rowconfigure(1, weight=1)
        headings = ctk.CTkFrame(self.plugin_page, height=34, fg_color=C['faint'], corner_radius=7)
        headings.grid(row=0, column=0, sticky='ew', padx=(0, 12))
        headings.grid_columnconfigure(0, weight=1)
        for col, value, width in [(0, '插件', 280), (1, '安装版本', 100), (2, '来源', 96), (3, '检查结果', 138), (4, '启用', 68)]:
            text(headings, value, size=12, color=C['muted'], width=width).grid(
                row=0, column=col, sticky='w', padx=(12 if col==0 else 4, 4), pady=5)
        self.rows = ctk.CTkScrollableFrame(self.plugin_page, fg_color='white', corner_radius=0,
            scrollbar_button_color='#DEE2E9', scrollbar_button_hover_color='#BFC6D2', height=180)
        self.rows.grid(row=1, column=0, sticky='nsew', pady=(4, 0))
        self.rows.grid_columnconfigure(0, weight=1)
        text(self.plugin_page, '开关管理原配置；检查版本仅用于预览兼容性，实际功能仍需启动后验证。',
             size=11, color=C['muted']).grid(row=2, column=0, sticky='w', padx=6, pady=(8, 0))
        self.build_backups()
        self.build_market()

    def build_market(self):
        self.market_page = ctk.CTkFrame(self.content, fg_color='transparent')
        self.market_page.grid_columnconfigure(0, weight=1)
        self.market_page.grid_rowconfigure(2, weight=1)
        filters = ctk.CTkFrame(self.market_page, fg_color='transparent')
        filters.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        filters.grid_columnconfigure(0, weight=1)
        self.market_search = ctk.CTkEntry(filters,
            placeholder_text='搜索插件、作者或功能…', height=44, border_width=1, corner_radius=9,
            border_color=C['line'], fg_color='white', font=(FONT, 14))
        self.market_search.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.market_search.bind('<KeyRelease>', self.schedule_search)
        self.market_category = ctk.CTkOptionMenu(filters, values=['全部分类'], width=152, height=44,
            fg_color=C['faint'], button_color=C['faint'], button_hover_color=C['line'],
            text_color=C['ink'], font=(FONT, 13), dropdown_font=(FONT, 13),
            dropdown_fg_color='white', dropdown_text_color=C['ink'],
            command=lambda _: self.render_market(reset=True))
        self.market_category.grid(row=0, column=1, padx=(0, 10))
        self.action(filters, '刷新市场', self.load_market, width=94).grid(row=0, column=2)
        self.market_summary = text(self.market_page, '读取公开插件目录，无需登录。', size=12, color=C['muted'])
        self.market_summary.grid(row=1, column=0, sticky='w', pady=(4, 10))
        self.market_rows = ctk.CTkScrollableFrame(self.market_page, fg_color='white', corner_radius=0,
            scrollbar_button_color='#DEE2E9', scrollbar_button_hover_color='#BFC6D2', height=130)
        self.market_rows.grid(row=2, column=0, sticky='nsew')
        self.market_rows.grid_columnconfigure((0, 1), weight=1, uniform='market')
        self.market_rows.bind('<Configure>', self.schedule_market_resize, add='+')
        self.market_empty = text(self.market_rows, '没有找到匹配的插件，试试其他关键词。', color=C['muted'])
        pager = ctk.CTkFrame(self.market_page, fg_color='transparent')
        pager.grid(row=3, column=0, sticky='ew', pady=(9, 0))
        text(pager, '社区目录  awesome-dsh-plugin.com', size=11, color=C['muted']).pack(side='left')
        self.market_next = button(pager, '下一页', lambda: self.market_turn(1), width=78)
        self.market_next.pack(side='right')
        self.market_page_label = text(pager, '1 / 1', width=78, anchor='center', size=11, color=C['muted'])
        self.market_page_label.pack(side='right')
        self.market_previous = button(pager, '上一页', lambda: self.market_turn(-1), width=78)
        self.market_previous.pack(side='right')

    def schedule_search(self, *_):
        if self.search_timer:
            self.after_cancel(self.search_timer)
            self.search_timer = None
        if self.market_search.get().strip().lower() != self.market_last_query:
            self.search_timer = self.after(160, lambda: self.render_market(reset=True))

    def load_market(self):
        def loaded(catalog):
            self.market_catalog = catalog
            self.market_category.configure(values=['全部分类']+list(catalog['categories'].values()))
            self.market_category.set('全部分类')
            self.render_market(reset=True)
            self.status.set(f"插件市场已连接，共 {len(catalog['items'])} 项。")
        self.background(market.fetch_catalog, loaded)

    def market_turn(self, delta):
        self.market_page_index += delta
        self.render_market()

    def render_market(self, reset=False):
        if self.search_timer:
            self.after_cancel(self.search_timer)
        self.search_timer = None
        if not self.market_catalog:
            return
        if reset:
            self.market_page_index = 0
        catalog = self.market_catalog
        query = self.market_search.get().strip().lower()
        self.market_last_query = query
        category = next((k for k,v in catalog['categories'].items() if v == self.market_category.get()), None)
        if self.market_index_catalog is not catalog:
            self.market_index = [(p, ' '.join((p['name'], p['npm'], p['owner'], p['description'])).lower())
                                 for p in catalog['items']]
            self.market_index_catalog = catalog
            self.market_filter_key = None
        if self.market_filter_key != (query, category):
            self.market_filtered = [p for p, searchable in self.market_index
                if (category is None or category in p['categories']) and (not query or query in searchable)]
            self.market_filter_key = (query, category)
        items = self.market_filtered
        pages = max(1, (len(items)+11)//12)
        self.market_page_index = max(0, min(self.market_page_index, pages-1))
        installed = {p['name'] for r in (self.report or {}).get('runtimes',[]) for p in r['plugins']}
        market_buttons = {card['action'] for card in self.market_cards}
        self.actions = [action for action in self.actions if action not in market_buttons and action.winfo_exists()]
        self.market_card_labels = []
        self.market_card_width = None
        self.market_summary.configure(text=f"{len(items):,} 个插件    /    GitHub Stars 来自 {catalog['updated'] or '未注明日期'} 的目录快照")
        page_items = items[self.market_page_index*12:(self.market_page_index+1)*12]
        for i, item in enumerate(page_items):
            if i == len(self.market_cards):
                self.market_cards.append(self.create_market_card(i))
            card = self.market_cards[i]
            card['row'].grid()
            card['item'] = item
            stars = item.get('stars')
            self.market_card_labels.append((card['title'], item['name'], card['description'], item['description'] or '作者暂未提供简介。'))
            category_name = next((catalog['categories'].get(c, c) for c in item['categories']), '社区插件')
            is_installed = item['npm'] in installed or item['name'] in installed
            state = 'disabled' if is_installed or self.busy else 'normal'
            signature = (item['name'], item['owner'], item['version'], stars, category_name,
                         item['url'], item['installable'], is_installed, state)
            if card['signature'] != signature:
                card['signature'] = signature
                owner = item['owner'] or '作者未提供'
                card['meta'].configure(text=owner+('  /  v'+item['version'] if item['version'] else ''))
                card['stars'].configure(text=f'☆  {stars:,} Stars' if stars is not None else '☆  Stars 暂无数据',
                                        text_color=C['accent'] if stars is not None else C['muted'])
                card['category'].configure(text=category_name)
                card['source'].configure(text='npm' if item['installable'] else 'GitHub' if urlsplit(item['url']).hostname == 'github.com' else '项目仓库')
                primary = not is_installed and item['installable']
                card['action'].configure(text='✓ 已安装' if is_installed else '安装' if item['installable'] else '详情',
                    state=state, fg_color=C['accent'] if primary else C['soft'],
                    hover_color=C['hover'] if primary else '#DBEBE2',
                    text_color='white' if primary else C['accent'],
                    text_color_disabled=C['green'] if is_installed else '#D3E5DC' if primary else C['muted'])
            if not is_installed:
                self.actions.append(card['action'])
        for card in self.market_cards[len(page_items):]:
            card['row'].grid_remove()
        if not items:
            self.market_empty.grid(row=0, column=0, columnspan=2, pady=35)
        else:
            self.market_empty.grid_remove()
        self.market_page_label.configure(text=f'{self.market_page_index+1} / {pages}')
        self.market_previous.configure(state='normal' if self.market_page_index else 'disabled')
        self.market_next.configure(state='normal' if self.market_page_index+1<pages else 'disabled')
        self.schedule_market_resize(delay=0)
        self.after_idle(lambda: self.market_rows._parent_canvas.yview_moveto(0))

    def create_market_card(self, index):
        row = ctk.CTkFrame(self.market_rows, fg_color='white', corner_radius=12,
                          border_width=1, border_color=C['line'], height=232, width=1)
        row.grid(row=index//2, column=index%2, sticky='nsew', padx=(0, 8) if index%2==0 else (8, 0), pady=(0, 16))
        row.grid_columnconfigure(0, weight=1)
        row.grid_propagate(False)
        card = dict(row=row, item=None, signature=None)
        card['title'] = text(row, '', size=17, bold=True, width=1, height=30)
        card['title'].grid(row=0, column=0, sticky='ew', padx=(20, 12), pady=(16, 0))
        card['meta'] = text(row, '', size=12, color=C['muted'], width=1, height=24)
        card['meta'].grid(row=1, column=0, columnspan=2, sticky='ew', padx=20)
        card['stars'] = text(row, '', size=13, color=C['accent'], height=26)
        card['stars'].grid(row=2, column=0, columnspan=2, sticky='w', padx=20, pady=(3, 4))
        card['description'] = text(row, '', size=13, color=C['muted'], height=65, width=1, justify='left', anchor='nw')
        card['description'].grid(row=3, column=0, columnspan=2, sticky='ew', padx=20, pady=(0, 10))
        card['category'] = badge(row, '', C['muted'], C['faint'])
        card['category'].grid(row=4, column=0, sticky='w', padx=20)
        card['source'] = text(row, '', size=11, color=C['muted'])
        card['source'].grid(row=4, column=1, sticky='e', padx=20)
        card['action'] = button(row, '', lambda: self.open_market_item(card['item']), width=86)
        card['action'].configure(height=32)
        card['action'].grid(row=0, column=1, padx=(0, 20), pady=(14, 0))
        return card

    def schedule_market_resize(self, event=None, delay=70):
        if self.market_resize_timer:
            self.after_cancel(self.market_resize_timer)
        self.market_resize_timer = self.after_idle(self.resize_market_cards) if delay == 0 else self.after(delay, self.resize_market_cards)

    def resize_market_cards(self, event=None):
        if self.market_resize_timer:
            self.after_cancel(self.market_resize_timer)
            self.market_resize_timer = None
        # Measure against the actual two-column width, including Windows scaling.
        width = self.market_rows.winfo_width() / self.market_rows._get_widget_scaling()
        card_width = max(330, width / 2 - 16)
        if card_width == self.market_card_width:
            return
        self.market_card_width = card_width
        for title, name, description, body in self.market_card_labels:
            fitted = fit_text(name, card_width - 140, self.market_title_font.measure)
            excerpt = wrap_preview(body, card_width - 44, self.market_body_font.measure)
            if title.cget('text') != fitted:
                title.configure(text=fitted)
            if description.cget('text') != excerpt:
                description.configure(text=excerpt)

    def open_market_item(self, item):
        if not self.busy:
            self.market_dialog = MarketDialog(self, item)

    def install_market_item(self, item):
        import market_install
        def installed(result):
            if self.market_dialog:
                self.market_dialog.destroy()
                self.market_dialog = None
            def refreshed(report):
                self.show(report)
                self.render_market()
                self.status.set(f"{result.get('name', item['npm'])} 已安装并完成声明检查。实际功能待启动后确认。")
            self.background(lambda: host.evaluate(host.load_config()), refreshed)
        self.background(lambda: market_install.install_plugin(host.load_config(), item), installed, refresh_on_error=True)
        self.status.set('正在备份并安装 '+item['npm']+'，请等待安装结果…')

    def build_backups(self):
        self.backup_page = ctk.CTkFrame(self.content, fg_color='transparent')
        self.backup_page.grid_columnconfigure(0, weight=1)
        text(self.backup_page, '熟悉的配置，继续保留', size=23, bold=True).grid(row=0, column=0, sticky='w')
        text(self.backup_page, '切换 DSH 版本时，继续使用同一份本机数据。',
             size=14, color=C['muted']).grid(row=1, column=0, sticky='w', pady=(4, 18))
        location = ctk.CTkFrame(self.backup_page, fg_color=C['faint'], corner_radius=10)
        location.grid(row=2, column=0, sticky='ew', pady=(0, 25))
        text(location, '固定配置目录', size=12, color=C['muted']).pack(anchor='w', padx=18, pady=(12, 2))
        self.home_path = text(location, '正在读取…', size=12, wraplength=900, justify='left')
        self.home_path.pack(anchor='w', padx=18, pady=(0, 12))
        columns = ctk.CTkFrame(self.backup_page, fg_color='transparent')
        columns.grid(row=3, column=0, sticky='nsew')
        columns.grid_columnconfigure((0, 1), weight=1, uniform='backups')
        retained = ctk.CTkFrame(columns, fg_color='transparent')
        retained.grid(row=0, column=0, sticky='nsew', padx=(0, 30))
        text(retained, '哪些设置会保留', size=17, bold=True).pack(anchor='w', pady=(0, 14))
        for title, detail in [('启用状态与侧栏设置', '沿用原 profile，已纳入配置快照'),
                              ('皮肤与提示词增强配置', '沿用原文件，尚未纳入快照'),
                              ('默认启动版本', '保存在托管器，重新打开仍会记住')]:
            text(retained, title, size=14).pack(anchor='w', pady=(0, 1))
            text(retained, detail, size=12, color=C['muted']).pack(anchor='w', pady=(0, 16))
        text(retained, '其他插件的私有存储尚未逐项验证。', size=12,
             color=C['muted']).pack(anchor='w', pady=(8, 0))
        history = ctk.CTkFrame(columns, fg_color='transparent')
        history.grid(row=0, column=1, sticky='nsew', padx=(20, 0))
        history.grid_columnconfigure(0, weight=1)
        text(history, '恢复历史配置', size=17, bold=True).grid(row=0, column=0, sticky='w', pady=(0, 14))
        text(history, '快照在本机加密保存', size=12, color=C['muted']).grid(row=1, column=0, sticky='w', pady=(0, 8))
        self.snapshots = ctk.CTkOptionMenu(history, values=['暂无备份'], width=320,
            fg_color=C['faint'], button_color=C['line'], button_hover_color='#DDE2EA',
            text_color=C['ink'], font=(FONT, 12), dropdown_font=(FONT, 12),
            dropdown_fg_color='white', dropdown_text_color=C['ink'], height=42, dynamic_resizing=False)
        self.snapshots.grid(row=2, column=0, sticky='ew')
        actions = ctk.CTkFrame(history, fg_color='transparent')
        actions.grid(row=3, column=0, sticky='w', pady=18)
        self.action(actions, '立即备份', self.backup, primary=True, width=122).pack(side='left', padx=(0, 10))
        self.action(actions, '恢复所选配置', self.restore, width=140).pack(side='left')
        text(history, '恢复前请正常退出 DSH。\n快照包含 profile 配置，不包含会话、附件、\n插件安装包及其他独立状态文件。',
             size=12, color=C['muted'], justify='left').grid(row=4, column=0, sticky='w')

    def build_footer(self):
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=4, column=0, sticky='ew', padx=34, pady=(12, 15))
        footer.grid_columnconfigure(0, weight=1)
        text(footer, textvariable=self.status, color=C['muted'], size=11,
             wraplength=750, justify='left').grid(row=0, column=0, sticky='w')
        button(footer, '详细报告', self.open_report, width=85).grid(row=0, column=1, sticky='e')

    def change_tab(self, value):
        self.market_page.grid_remove()
        self.backup_page.grid_remove()
        self.plugin_page.grid_remove()
        if value == '插件清单':
            self.notice.grid()
            self.plugin_page.grid()
            self.runtime_menu.pack(side='right')
            self.count_label.pack(side='left', padx=14)
        else:
            self.notice.grid_remove()
            self.runtime_menu.pack_forget()
            self.count_label.pack_forget()
            if value == '插件市场':
                self.market_page.grid(row=1, column=0, sticky='nsew', padx=22, pady=(0, 16))
                if self.market_catalog is None:
                    self.load_market()
            else:
                self.backup_page.grid(row=1, column=0, sticky='nsew', padx=28, pady=(18, 24))
                self.refresh_snapshots()

    def background(self, fn, done, refresh_on_error=False):
        if self.busy:
            return
        self.busy = True
        self.refresh_after_error = refresh_on_error
        self.status.set('正在处理，请稍候…')
        self.actions = [item for item in self.actions if item.winfo_exists()]
        for item in self.actions:
            if item.winfo_exists():
                item.configure(state='disabled')
        def run():
            try:
                self.jobs.put((done, fn(), None))
            except Exception as exc:
                self.jobs.put((done, None, str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            done, result, error = self.jobs.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            refresh_on_error = self.refresh_after_error
            self.refresh_after_error = False
            for item in self.actions:
                if item.winfo_exists():
                    item.configure(state='normal')
            if error:
                if self.version_dialog:
                    self.version_dialog.close()
                if self.market_catalog is None and self.tabs.get() == '插件市场':
                    self.market_summary.configure(text='目录读取失败，可以点击「刷新市场」重试。')
                if self.report:
                    try:
                        self.refresh_preference()
                        self.render_plugins()
                    except Exception as exc:
                        error += '\n无法刷新默认版本：'+str(exc)
                self.status.set(error)
                messagebox.showwarning('操作未完成', error, parent=self.market_dialog or self)
                if refresh_on_error:
                    def refreshed(report):
                        self.show(report)
                        self.render_market()
                        self.status.set(error)
                    self.background(lambda: host.evaluate(host.load_config()), refreshed)
            else:
                done(result)
            if self.version_dialog and self.version_dialog.winfo_exists():
                self.version_dialog.update_selection()
        self.after(80, self.poll)

    def check(self):
        self.background(lambda: host.evaluate(host.load_config()), self.show)

    def show(self, report):
        self.report = report
        running = [r for r in report['runtimes'] if any(same_path(r['exe'], p['exe']) for p in report['running'])]
        self.current_version.configure(text=' / '.join(r.get('runtime', '未知版本') for r in running) or '尚未运行')
        mismatch = report.get('profile_mismatch')
        self.running_badge.configure(text='配置目录不同' if mismatch else '●  运行中' if running else '未启动',
            text_color=C['amber'] if mismatch else C['green'] if running else C['muted'],
            fg_color=C['amber_bg'] if mismatch else C['green_bg'] if running else C['faint'])
        self.refresh_preference()
        self.version_count.configure(text=f"本机已识别 {len(report['runtimes'])} 个版本")
        latest = report['runtimes'][0]
        if mismatch:
            notice = '运行中的配置目录不同，请正常退出 DSH 后从托管入口打开。'
        elif latest.get('error'):
            notice = '新版检查未完成，请在版本面板查看原因。'
        elif latest['blockers']:
            available = any(r['eligible_for_trial'] for r in report['runtimes'][1:])
            notice = f"{latest.get('runtime', '新版')} 有 {len(latest['blockers'])} 项插件待适配。" + ('保留版本可继续使用。' if available else '请在版本面板查看原因。')
        else:
            notice = f"{latest.get('runtime', '新版')} 已通过启动前检查，可以在「切换版本」中选择。"
        self.notice_text.configure(text=notice)
        ready = latest['eligible_for_trial'] and not mismatch
        tone, bg = (C['green'], C['green_bg']) if ready else (C['amber'], C['amber_bg'])
        self.notice.configure(fg_color=bg)
        self.notice_text.configure(text_color=tone)
        self.notice_button.configure(fg_color=bg, text_color=tone)
        self.runtime_choices = {f"检查版本  {r.get('runtime', '未知版本')}"+(f' ({i+1})' if not r.get('runtime') else ''):r
                                for i,r in enumerate(report['runtimes'])}
        prior = self.view_runtime.get()
        self.runtime_menu.configure(values=list(self.runtime_choices))
        self.view_runtime.set(prior if prior in self.runtime_choices else next(iter(self.runtime_choices)))
        self.render_plugins()
        self.refresh_snapshots()
        stamp = dt.datetime.fromisoformat(report['at'].replace('Z', '+00:00')).astimezone()
        self.status.set('已检查 '+stamp.strftime('%H:%M')+'   ·   配置保存在原目录')
        if self.tabs.get() == '插件市场' and self.market_catalog is None:
            self.after(1, self.load_market)

    def refresh_preference(self):
        cfg = host.load_config()
        preferred = next((r for r in self.report['runtimes'] if same_path(r['exe'], cfg.get('preferred_exe'))), None)
        default = '默认启动  '+preferred.get('runtime', '未知版本') if preferred else '自动选择可用版本'
        self.default_label.configure(text=default+'\n插件与设置沿用原目录', justify='right')
        self.home_path.configure(text=str(cfg['home']))

    def render_plugins(self):
        if not self.report:
            return
        runtime = self.runtime_choices[self.view_runtime.get()]
        plugins = sorted(runtime['plugins'], key=lambda p: (
            p['pending_enabled'] if p.get('pending_enabled') is not None else p.get('enabled')) is False)
        if not hasattr(self, 'plugin_row_cache'):
            self.plugin_row_cache = {}
        cache = self.plugin_row_cache
        names = tuple(plugin['name'] for plugin in plugins)
        layout_changed = set(names) != set(getattr(self, 'plugin_row_order', ()))
        for name in set(cache) - set(names):
            stale = cache.pop(name)
            stale['row'].destroy()
            stale['divider'].destroy()

        def update(widget, **values):
            changed = {key: value for key, value in values.items() if widget.cget(key) != value}
            if changed:
                widget.configure(**changed)

        labels = {'metadata-ok':'声明检查通过', 'version-blocked':'版本待适配',
                  'dependency-blocked':'依赖待适配', 'missing':'安装文件缺失', 'loader-skipped':'加载器跳过'}
        update(self.count_label, text=f"{len(runtime['plugins'])} 个插件")
        error = runtime.get('error')
        error_label = getattr(self, 'plugin_error_label', None)
        if error:
            if error_label is None:
                error_label = self.plugin_error_label = text(self.rows, error, color=C['amber'], wraplength=780, justify='left')
                error_label.grid(row=0, column=0, padx=10, pady=20)
            else:
                update(error_label, text=error)
        elif error_label is not None:
            error_label.destroy()
            self.plugin_error_label = None

        active_toggles = []
        for i, plugin in enumerate(plugins):
            full_version = plugin.get('version', '—')
            short_version = full_version.split('+')[0]+(' +补丁' if '+' in full_version else '')
            source = plugin.get('source', {'label':'待检查'})
            disabled = plugin.get('enabled') is False
            ok = plugin['status']=='metadata-ok'
            pending = plugin.get('pending_enabled')
            checked = not disabled if pending is None else pending
            supported = plugin.get('enabled') is not None and plugin.get('toggle_supported') is not False
            entry = cache.get(plugin['name'])
            if entry is None:
                row = ctk.CTkFrame(self.rows, fg_color='white', corner_radius=0, height=68)
                row.grid_columnconfigure(0, weight=1)
                name = display_name(plugin['name'])
                identity = ctk.CTkFrame(row, fg_color='transparent', width=280, height=46)
                identity.grid(row=0, column=0, sticky='ew', padx=(8, 4), pady=9)
                identity.pack_propagate(False)
                icon = text(identity, name[:1], size=17, bold=True, color=C['accent'], fg_color=C['soft'],
                            width=37, height=38, corner_radius=10, anchor='center')
                icon.pack(side='left', padx=(0, 12))
                identity_text = ctk.CTkFrame(identity, fg_color='transparent')
                identity_text.pack(side='left', fill='x', expand=True)
                text(identity_text, name, size=14, bold=True, height=24).pack(anchor='w', fill='x')
                text(identity_text, plugin['name'], size=11, color=C['muted'], height=20).pack(anchor='w', fill='x')
                version = text(row, short_version, size=12, color=C['muted'], width=100)
                version.grid(row=0, column=1, padx=4, sticky='w')
                source_cell = ctk.CTkFrame(row, fg_color='transparent', width=96, height=46)
                source_cell.grid(row=0, column=2, padx=4, sticky='w')
                source_cell.pack_propagate(False)
                state_cell = ctk.CTkFrame(row, fg_color='transparent', width=138, height=30)
                state_cell.grid(row=0, column=3, padx=4, sticky='w')
                state_cell.grid_propagate(False)
                state = badge(state_cell, labels.get(plugin['status'], '尚未检查'),
                              C['muted'] if disabled else C['green'] if ok else C['amber'],
                              C['faint'] if disabled else C['green_bg'] if ok else C['amber_bg'])
                state.grid(row=0, column=0)
                toggle_cell = ctk.CTkFrame(row, fg_color='transparent', width=68, height=46)
                toggle_cell.grid(row=0, column=4, padx=4, sticky='w')
                toggle_cell.pack_propagate(False)
                value = tk.BooleanVar(value=checked)
                entry = {'row':row, 'plugin':plugin, 'version':version, 'source_cell':source_cell,
                         'state':state, 'value':value, 'toggle_cell':toggle_cell,
                         'repository':None, 'note':None, 'repository_visible':False, 'note_visible':False,
                         'divider':ctk.CTkFrame(self.rows, height=1, fg_color=C['line'])}
                source_link = button(source_cell, source.get('label', '未知'),
                                     lambda current=entry: self.show_source(current['plugin']), width=84)
                source_link.configure(height=25, fg_color=C['faint'], text_color=C['accent'], font=(FONT, 11))
                source_link.pack(anchor='w')
                entry['source'] = source_link
                toggle = ctk.CTkSwitch(toggle_cell, text='', variable=value, width=56, height=28,
                    switch_width=44, switch_height=24, border_width=3, button_length=0,
                    fg_color='#E0E6E2', progress_color='#BBDDCF',
                    button_color=C['accent'] if checked else '#8A9991',
                    button_hover_color=C['hover'] if checked else '#718078',
                    command=lambda current=entry: self.toggle_plugin(current['plugin'], current['value']))
                toggle.pack(anchor='w')
                entry['toggle'] = toggle
                cache[plugin['name']] = entry
            entry['plugin'] = plugin
            grid_row = i*2 + (2 if error else 0)
            if entry.get('grid_row') != grid_row:
                entry['row'].grid(row=grid_row, column=0, sticky='ew')
                entry['divider'].grid(row=grid_row+1, column=0, sticky='ew', padx=8)
                entry['grid_row'] = grid_row
            update(entry['version'], text=short_version)
            update(entry['source'], text=source.get('label', '未知'))
            update(entry['state'], text=labels.get(plugin['status'], '尚未检查'),
                   text_color=C['muted'] if disabled else C['green'] if ok else C['amber'],
                   fg_color=C['faint'] if disabled else C['green_bg'] if ok else C['amber_bg'])
            if entry['value'].get() != checked:
                entry['value'].set(checked)
            update(entry['toggle'], state='normal' if supported and not self.busy else 'disabled',
                   button_color=C['accent'] if checked else '#8A9991',
                   button_hover_color=C['hover'] if checked else '#718078')
            repository_text = ('GitHub 仓库' if urlsplit(source['repository_url']).hostname == 'github.com' else '项目仓库') if source.get('repository_url') else ''
            note = '待重启' if pending is not None else ('自动' if plugin.get('enabled_state') == 'conditional' else '不可切换') if not supported else ''
            for key, caption, parent, color in (
                    ('repository', repository_text, entry['source_cell'], C['muted']),
                    ('note', note, entry['toggle_cell'], C['amber'] if pending is not None else C['muted'])):
                if caption:
                    if entry[key] is None:
                        entry[key] = text(parent, caption, size=10, color=color, height=18 if key=='repository' else 17)
                    else:
                        update(entry[key], text=caption, text_color=color)
                    if not entry[key+'_visible']:
                        entry[key].pack(anchor='w', padx=5 if key=='repository' else 0)
                        entry[key+'_visible'] = True
                elif entry[key+'_visible']:
                    entry[key].pack_forget()
                    entry[key+'_visible'] = False
            if supported:
                active_toggles.append(entry['toggle'])
        row_toggles = {entry['toggle'] for entry in cache.values()}
        self.actions = [item for item in self.actions if item not in row_toggles and item.winfo_exists()]
        self.actions.extend(active_toggles)
        runtime_changed = self.view_runtime.get() != getattr(self, 'plugin_rows_runtime', None)
        if layout_changed or runtime_changed:
            self.after_idle(lambda: self.rows._parent_canvas.yview_moveto(0))
        self.plugin_row_order = names
        self.plugin_rows_runtime = self.view_runtime.get()

    def toggle_plugin(self, plugin, value):
        if self.busy:
            value.set(plugin.get('pending_enabled', plugin.get('enabled') is not False))
            return
        enabled = bool(value.get())
        def saved(result):
            verb = '启用' if enabled else '禁用'
            message = display_name(plugin['name'])+(' 已保存待'+verb+'的选择' if result.get('restart_required') else ' 已设为'+verb)
            if result.get('restart_required'):
                message += '；正常退出后点「打开 DSH」应用。'
            else:
                message += '，下次启动时生效。'
            def refreshed(report):
                self.show(report)
                self.status.set(message)
            self.background(lambda: host.evaluate(host.load_config()), refreshed)
        self.background(lambda: host.set_plugin_enabled(host.load_config(), plugin['name'], enabled), saved)

    def show_source(self, plugin):
        SourceDialog(self, plugin)

    def open_report(self):
        report = host.STATE / 'report.html'
        if report.exists():
            os.startfile(report)
        else:
            self.status.set('检查完成后即可查看报告。')

    def open_versions(self):
        if not self.report or self.busy:
            return
        if self.version_dialog and self.version_dialog.winfo_exists():
            self.version_dialog.focus()
            return
        self.version_dialog = VersionDialog(self)

    def switch_done(self, result):
        if self.version_dialog:
            self.version_dialog.destroy()
            self.version_dialog = None
        if result['status'] == 'needs-exit':
            message = '默认版本已保存。请正常退出当前 DSH，再点「打开 DSH」完成切换。'
        elif result['status'] in ('reused', 'existing-managed-instance'):
            message = '所选版本已在运行，默认启动版本已保存。' if result['status']=='reused' else '已打开正在运行的 DSH。'
        else:
            message = '已发起启动，请在 DSH 中确认插件功能。'
        def refreshed(report):
            self.show(report)
            self.status.set(message)
        self.background(lambda: host.evaluate(host.load_config()), refreshed)

    def open_dsh(self):
        self.background(lambda: host.smart_launch(host.load_config()), self.switch_done)

    def refresh_snapshots(self, preferred=None):
        ids = sorted([p.name for p in (host.STATE/'snapshots').glob('*') if (p/'snapshot.json').exists()], reverse=True)
        previous = preferred or self.snapshot_ids.get(self.snapshots.get())
        self.snapshot_ids = {}
        for sid in ids:
            try:
                stamp = dt.datetime.strptime(sid[:15], '%Y%m%d-%H%M%S').strftime('%Y/%m/%d  %H:%M:%S')
            except ValueError:
                stamp = sid
            self.snapshot_ids[stamp+'   ·   '+sid[-6:]] = sid
        labels = list(self.snapshot_ids)
        self.snapshots.configure(values=labels or ['暂无备份'])
        chosen = next((k for k,v in self.snapshot_ids.items() if v==previous), None)
        self.snapshots.set(chosen or (labels[0] if labels else '暂无备份'))

    def backup(self):
        def saved(meta):
            self.refresh_snapshots(meta['id'])
            self.status.set('配置已加密备份并完成校验。')
        self.background(lambda: host.snapshot(host.load_config()), saved)

    def restore(self):
        sid = self.snapshot_ids.get(self.snapshots.get())
        if not sid:
            self.status.set('请先创建或选择一个配置备份。')
            return
        def restored(result):
            def refreshed(report):
                self.show(report)
                self.render_market()
                count = result.get('canceled_pending_plugins', 0)
                self.status.set('所选配置已恢复并完成校验。'+(f'已取消 {count} 项待应用开关。' if count else ''))
            self.background(lambda: host.evaluate(host.load_config()), refreshed)
        self.background(lambda: host.restore(host.load_config(), sid), restored)

    def close(self):
        if self.busy:
            self.status.set('操作正在进行，完成后即可关闭窗口。')
        else:
            self.destroy()


class VersionDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.panel = parent
        self.title('切换 DSH 版本')
        self.geometry('640x490')
        self.resizable(False, False)
        self.configure(fg_color=C['bg'])
        self.transient(parent)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda _: self.close())
        self.cards = []
        cfg = host.load_config()
        self.selected = tk.StringVar(value=cfg.get('preferred_exe', cfg['fallback_exe']))
        text(self, '切换 DSH 版本', size=23, bold=True).pack(anchor='w', padx=28, pady=(26, 4))
        text(self, '插件与设置沿用原目录，选择会成为默认启动版本。', color=C['muted'], size=12).pack(anchor='w', padx=28, pady=(0, 20))
        for runtime in parent.report['runtimes']:
            card = ctk.CTkFrame(self, fg_color='white', corner_radius=12, border_width=1, border_color=C['line'])
            card.pack(fill='x', padx=26, pady=(0, 12))
            card.grid_columnconfigure(1, weight=1)
            radio = ctk.CTkRadioButton(card, text='', variable=self.selected, value=runtime['exe'],
                command=self.update_selection, width=22, radiobutton_width=20, radiobutton_height=20,
                fg_color=C['accent'], hover_color=C['hover'], border_width_checked=5, border_width_unchecked=2)
            radio.grid(row=0, column=0, rowspan=2, padx=(17, 10), pady=16)
            parent.actions.append(radio)
            title = ctk.CTkFrame(card, fg_color='transparent')
            title.grid(row=0, column=1, sticky='w', pady=(15, 3))
            text(title, runtime.get('runtime', '无法读取版本'), size=19, bold=True).pack(side='left')
            active = any(same_path(runtime['exe'], p['exe']) for p in parent.report['running'])
            if active:
                badge(title, '运行中', C['green'], C['green_bg']).pack(side='left', padx=10)
            if same_path(runtime['exe'], cfg.get('preferred_exe')):
                badge(title, '默认', C['accent'], C['soft']).pack(side='left')
            description = '保留版本' if same_path(runtime['exe'], cfg['fallback_exe']) else '当前安装版本'
            ready = runtime['eligible_for_trial']
            description += '   /   '+('声明检查通过' if ready else '检查未完成' if runtime.get('error') else f"{len(runtime['blockers'])} 项插件待适配")
            text(card, description, size=12, color=C['green'] if ready else C['amber']).grid(row=1, column=1, sticky='w', pady=(0, 16))
            self.cards.append((card, runtime))
        self.detail = text(self, '', size=12, color=C['muted'], wraplength=570, justify='left')
        self.detail.pack(fill='x', padx=28, pady=(2, 12))
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.pack(side='bottom', fill='x', padx=28, pady=24)
        self.apply_button = parent.action(footer, '使用此版本', self.apply, primary=True, width=175)
        self.apply_button.pack(side='right')
        self.inspect_button = parent.action(footer, '查看插件检查', self.inspect, width=130)
        self.inspect_button.pack(side='left')
        self.update_selection()
        self.after(150, self.grab_set)

    def update_selection(self):
        selected = next((r for _,r in self.cards if same_path(r['exe'], self.selected.get())), None)
        for card, runtime in self.cards:
            card.configure(border_color=C['accent'] if runtime is selected else C['line'],
                           border_width=2 if runtime is selected else 1)
        if not selected:
            self.apply_button.configure(state='disabled')
            return
        active = self.panel.report['running']
        ready = selected['eligible_for_trial']
        if not ready:
            detail = selected.get('error') or ('待适配插件：'+ '、'.join(display_name(x) for x in selected['blockers'][:3]) + (' 等。' if len(selected['blockers'])>3 else '。'))
            self.detail.configure(text=detail+'\n请先处理检查项，再切换到这个版本。', text_color=C['amber'])
            value = '暂不可切换'
        elif active and not all(same_path(x['exe'], selected['exe']) for x in active):
            self.detail.configure(text='选择后保存为默认版本。请先正常退出正在运行的 DSH，再点「打开 DSH」完成切换。', text_color=C['muted'])
            value = '设为下次启动版本'
        elif active:
            self.detail.configure(text='此版本正在运行。设为默认后，桌面的 DSH 入口会优先使用它。', text_color=C['muted'])
            value = '设为默认版本'
        else:
            self.detail.configure(text='启动前会重新检查并备份配置。声明检查通过不代表所有插件功能都已经验证。', text_color=C['muted'])
            value = '使用此版本启动'
        self.apply_button.configure(text=value, fg_color=C['accent'] if ready else C['line'],
            text_color_disabled=C['muted'], state='normal' if ready and not self.panel.busy else 'disabled')

    def apply(self):
        exe = self.selected.get()
        self.panel.background(lambda: host.switch_version(host.load_config(), exe), self.panel.switch_done)

    def inspect(self):
        for label, runtime in self.panel.runtime_choices.items():
            if same_path(runtime['exe'], self.selected.get()):
                self.panel.view_runtime.set(label)
                break
        self.panel.tabs.set('插件清单')
        self.panel.change_tab('插件清单')
        self.panel.render_plugins()
        self.close()

    def close(self):
        if not self.panel.busy:
            self.panel.version_dialog = None
            self.destroy()


class SourceDialog(ctk.CTkToplevel):
    def __init__(self, parent, plugin):
        super().__init__(parent)
        self.title('插件来源')
        self.geometry('620x390')
        self.resizable(False, False)
        self.configure(fg_color=C['bg'])
        self.transient(parent)
        self.bind('<Escape>', lambda _: self.destroy())
        source = plugin.get('source', {})
        text(self, display_name(plugin['name']), size=22, bold=True).pack(anchor='w', padx=26, pady=(24, 3))
        text(self, plugin['name'], size=11, color=C['muted']).pack(anchor='w', padx=26, pady=(0, 15))
        details = ctk.CTkTextbox(self, fg_color='white', text_color=C['ink'], font=(FONT, 12),
                                corner_radius=12, height=175, wrap='word')
        details.pack(fill='both', expand=True, padx=26)
        body = '安装来源：'+source.get('label', '尚未识别')+'\n\n'+source.get('location', '未提供来源位置')
        repository = source.get('repository_url')
        if repository:
            body += '\n\n声明的项目仓库：\n'+repository
        if plugin.get('toggle_reason'):
            body += '\n\n启用控制：'+plugin['toggle_reason']
        body += '\n\n安装来源与项目仓库分别显示；仓库地址不等于本次安装来源。'
        details.insert('1.0', body)
        details.configure(state='disabled')
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.pack(fill='x', padx=26, pady=20)
        if repository and repository.startswith(('https://', 'http://')):
            button(footer, '打开项目仓库', lambda: webbrowser.open(repository), primary=True, width=140).pack(side='left')
        button(footer, '关闭', self.destroy, width=90).pack(side='right')
        self.after(150, self.grab_set)


class MarketDialog(ctk.CTkToplevel):
    def __init__(self, parent, item):
        super().__init__(parent)
        self.panel = parent
        self.title('插件市场 · '+item['name'])
        self.geometry('700x560')
        self.resizable(False, False)
        self.configure(fg_color=C['bg'])
        self.transient(parent)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda _: self.close())
        text(self, item['name'], size=23, bold=True, wraplength=640, justify='left').pack(anchor='w', padx=28, pady=(26, 4))
        text(self, item['owner']+'    '+item['version'], size=13, color=C['muted']).pack(anchor='w', padx=28, pady=(0, 4))
        stars = item.get('stars')
        star_label = f'☆  {stars:,} GitHub Stars' if stars is not None else '☆  GitHub Stars 暂无数据'
        text(self, star_label+'    /    目录快照 '+(item.get('stars_as_of') or '日期未提供'),
             size=12, color=C['accent']).pack(anchor='w', padx=28, pady=(0, 16))
        detail = ctk.CTkTextbox(self, fg_color='white', text_color=C['ink'], font=(FONT, 13), corner_radius=12, wrap='word')
        detail.pack(fill='both', expand=True, padx=26)
        body = item['description'] or '暂无简介'
        if item['npm']:
            body += '\n\n安装包：'+item['npm']+'@'+item['version']+'\n来源：npm'
        if item['url']:
            body += '\n\n项目仓库：'+item['url']
        body += '\n\n安装前请正常退出 DSH。托管器会备份配置，按所选版本安装，并使用 DSH 的包管理核心检查兼容性。'
        if not item['installable']:
            body += '\n\n这项未提供可固定版本的 npm 包，可打开项目仓库查看安装说明。'
        detail.insert('1.0', body)
        detail.configure(state='disabled')
        text(self, '已安装的插件保持原样；市场安装不覆盖本地同名插件。',
             size=11, color=C['muted']).pack(anchor='w', padx=28, pady=(12, 2))
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.pack(fill='x', padx=28, pady=20)
        if item['url']:
            button(footer, '项目仓库', lambda: webbrowser.open(item['url']), width=106).pack(side='left')
        if item['installable']:
            parent.action(footer, '安装到托管目录', lambda: parent.install_market_item(item),
                          primary=True, width=158).pack(side='right')
        self.after(150, self.grab_set)

    def close(self):
        if not self.panel.busy:
            self.panel.market_dialog = None
            self.destroy()


def main():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    panel_mutex = kernel.CreateMutexW(None, False, 'Local\\DSHPluginHostPanel')
    if ctypes.get_last_error() == 183:
        return
    app = Panel()
    app.mainloop()
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle(panel_mutex)


if __name__ == '__main__':
    main()
