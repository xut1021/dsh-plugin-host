"""Install catalog npm releases through DSH's shared offline package operations."""
import json
import os
from pathlib import Path
import subprocess

import host
import market


def checked_item(item, catalog):
    """A UI card is a claim; the newly fetched catalog remains the authority."""
    if not isinstance(item, dict):
        raise ValueError('请选择市场中的插件。')
    matches = [row for row in catalog['items'] if row.get('url') == item.get('url')
               and row.get('npm') == item.get('npm')]
    if len(matches) != 1 or not matches[0].get('installable'):
        raise RuntimeError('这个插件没有可安装的明确 npm 版本，或已不在市场目录中。')
    row = matches[0]
    if row['version'] != item.get('version'):
        raise RuntimeError('市场版本已变化，请刷新目录后重新选择。')
    if not market.PACKAGE.fullmatch(row['npm']) or not market.VERSION.fullmatch(row['version']):
        raise RuntimeError('市场插件的软件包名称或版本无效。')
    return row


def choose_runtime(config, profile):
    preference = config.get('preferred_exe')
    candidates = list(dict.fromkeys(path for path in
        [preference, config['fallback_exe'], config['current_exe']] if path))
    allowed = {os.path.normcase(str(Path(config[key]).resolve())) for key in ('fallback_exe', 'current_exe')}
    for path in candidates:
        if os.path.normcase(str(Path(path).resolve())) not in allowed:
            continue
        try:
            probe = host.probe(path, profile)
        except Exception:
            continue
        if probe.get('compatibilityApi') is True and not any(
                row['status'] != 'metadata-ok' and row.get('enabled') is not False for row in probe['plugins']):
            return Path(path), probe
    raise RuntimeError('现有版本未通过插件检查，或缺少版本检查接口；请先处理兼容问题再安装。')


def run_installer(exe, profile, home, name, version, launch_env=None):
    root = exe.parent / 'resources/app.asar/dsh'
    pnpm = exe.parent / 'resources/runtime/pnpm/bin/pnpm.cjs'
    if not pnpm.is_file():
        raise RuntimeError('这个 DSH 版本缺少随附包管理器，无法安装。')
    env = os.environ.copy()
    env.update(launch_env or {})
    env.update({'ELECTRON_RUN_AS_NODE': '1', 'DSH_HOME': str(home),
                'DSH_DESKTOP_NODE_EXECUTABLE': str(exe)})
    env['PATH'] = str(exe.parent / 'resources/runtime/bin') + os.pathsep + env.get('PATH', '')
    result = subprocess.run([str(exe), '--expose-internals', str(host.ROOT / 'market_install.mjs'),
        str(root), str(profile), str(home), name, version, str(pnpm)], env=env,
        capture_output=True, encoding='utf-8', errors='replace', creationflags=host.NO_WINDOW,
        timeout=720)
    frames = [line for line in result.stdout.splitlines() if line.startswith('{')]
    if not frames:
        raise RuntimeError('安装进程没有返回可识别结果；可能已有部分文件变化，请查看配置备份后重新检查。')
    data = json.loads(frames[-1])
    if not data.get('ok') or result.returncode:
        detail = '目标版本与 DSH 不兼容。' if data.get('incompatible') else '包管理器未完成安装。'
        raise RuntimeError(detail + ' 安装前的加密配置备份已保留；磁盘包文件可能已有变化，未执行自动整包回滚。'
                           + (' 诊断：' + data['logPath'] if data.get('logPath') else ''))
    return data


@host.serialized
def install_plugin(config, item):
    if host.running_hosts():
        raise RuntimeError('请先正常退出 DSH，再安装插件。托管面板可以保持打开。')
    selected = checked_item(item, market.fetch_catalog())
    profile = Path(config['home']) / 'profiles/desktop'
    manifest = json.loads((profile / 'package.json').read_text(encoding='utf-8'))
    name, version = selected['npm'], selected['version']
    installed = set().union(*(manifest.get(field, {}) for field in
        ('dependencies', 'devDependencies', 'optionalDependencies')))
    if name in installed or (profile / 'node_modules' / name / 'package.json').exists():
        raise RuntimeError('这个插件已经安装；市场安装不会覆盖已有版本或本地修改。')
    exe, before = choose_runtime(config, profile)
    saved = host.snapshot(config, 'before-market-install')
    if host.running_hosts():
        raise RuntimeError('DSH 已启动，安装已停止；请先正常退出。')
    try:
        result = run_installer(exe, profile, config['home'], name, version, config.get('launch_env'))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('安装等待超时；安装前配置备份已保留。请重新检查插件，磁盘包文件可能已有变化。') from exc
    after = host.probe(exe, profile)
    row = next((row for row in after['plugins'] if row['name'] == name), None)
    if not row or row.get('version') != version or row.get('status') != 'metadata-ok' or not row.get('bundled'):
        raise RuntimeError('软件包已写入，但安装后的插件声明检查未通过；请查看检查报告和安装前备份。')
    previous = {row['name']: row for row in before['plugins']}
    new_blockers = [row['name'] for row in after['plugins'] if row.get('enabled') is not False
        and row['status'] != 'metadata-ok' and previous.get(row['name'], {}).get('status') == 'metadata-ok']
    if new_blockers:
        raise RuntimeError('安装后其他插件的检查状态发生变化，请重新检查后再启动。安装前配置备份已保留。')
    return {'status': 'installed-not-verified', 'name': name, 'version': version,
            'snapshot': saved['id'], 'runtime': after.get('runtime'), 'exe': str(exe),
            'source': selected['url'], 'logPath': result.get('logPath'), 'functionality': 'unverified'}
