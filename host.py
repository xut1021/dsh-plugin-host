"""Windows-local DSH profile host. Metadata checks never claim functional compatibility."""
from __future__ import annotations
import argparse
import base64
import ctypes
from ctypes import wintypes
import datetime as dt
from functools import wraps
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state'
CONFIG_FILES = ('package.json', 'cordis.yml', 'cordis.patch.yml', 'pnpm-lock.yaml',
                'pnpm-workspace.yaml', 'compatibility.json')
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
LABELS = {'metadata-ok':'元数据检查通过 / 功能待验证', 'missing':'安装文件缺失',
          'version-blocked':'版本声明被 DSH 拒绝', 'loader-skipped':'加载器跳过',
          'dependency-blocked':'依赖被阻断'}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def load_config(check_paths=False):
    try:
        config=json.loads((ROOT/'local.json').read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise RuntimeError('缺少 local.json。请先复制 local.example.json 为 local.json，并填写本机 DSH 数据目录和两个版本的完整路径。') from None
    except (json.JSONDecodeError,UnicodeDecodeError):
        raise RuntimeError('local.json 不是有效的 UTF-8 JSON，请检查格式；Windows 路径中的反斜杠需要转义。') from None
    return validate_config(config,check_paths)

def validate_config(config,check_paths=False):
    if not isinstance(config,dict):raise RuntimeError('local.json 顶层必须是 JSON 对象。')
    for key in ('home','current_exe','fallback_exe'):
        value=config.get(key)
        if not isinstance(value,str) or not value.strip() or not Path(value).is_absolute():
            raise RuntimeError('local.json 的 '+key+' 必须填写完整的绝对路径。')
    env=config.get('launch_env',{})
    if not isinstance(env,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in env.items()):
        raise RuntimeError('local.json 的 launch_env 必须是名称和值均为字符串的 JSON 对象。')
    if env.get('DSH_HOME',config['home'])!=config['home']:
        raise RuntimeError('launch_env 中的 DSH_HOME 必须与 home 一致，避免插件配置目录错位。')
    if config.get('preferred_exe') is None:config.pop('preferred_exe',None)
    elif not isinstance(config['preferred_exe'],str):
        raise RuntimeError('local.json 的 preferred_exe 必须是路径字符串或省略。')
    if check_paths:
        if not (Path(config['home'])/'profiles/desktop/package.json').is_file():
            raise RuntimeError('home 下没有 profiles/desktop/package.json，请填写已有 DSH 数据目录，不要填写程序安装目录。')
        for key in ('current_exe','fallback_exe'):
            exe=Path(config[key])
            if not exe.is_file():raise RuntimeError(key+' 指向的 DSH 程序不存在，请核对完整路径。')
            if not (exe.parent/'resources/app.asar').is_file():
                raise RuntimeError(key+' 同目录下缺少 resources/app.asar；此工具需要完整的 DSH 桌面安装。')
    return config

def powershell_executable():
    candidates=[shutil.which('pwsh.exe'),shutil.which('pwsh'),
        str(Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'PowerShell/7/pwsh.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():return candidate
    raise RuntimeError('未找到 PowerShell 7。请安装 PowerShell 7，并确保 pwsh.exe 位于 PATH 或 Program Files/PowerShell/7。')

def serialized(fn):
    """Windows mutex is reentrant on the owning thread, including restore -> snapshot."""
    @wraps(fn)
    def call(*args,**kwargs):
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        k.CreateMutexW.restype=wintypes.HANDLE
        k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        k.WaitForSingleObject.restype=wintypes.DWORD
        k.ReleaseMutex.argtypes=[wintypes.HANDLE]
        k.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=k.CreateMutexW(None,False,'Local\\DSHPluginHostProfileWrite')
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        acquired=k.WaitForSingleObject(handle,5000) in (0,0x80)
        try:
            if not acquired:raise RuntimeError('另一项备份或恢复正在进行，请稍后重试。')
            return fn(*args,**kwargs)
        finally:
            if acquired:k.ReleaseMutex(handle)
            k.CloseHandle(handle)
    return call

def fingerprint(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

def profile_hashes(profile):
    return {name:fingerprint(Path(profile)/name) for name in CONFIG_FILES}

def inventory(profile):
    profile=Path(profile)
    meta=json.loads((profile/'package.json').read_text(encoding='utf-8'))
    result={}
    for name in meta.get('dependencies',{}):
        path=profile/'node_modules'/name/'package.json'
        result[name]=fingerprint(path)
    return result

def dpapi(data, decrypt=False):
    """Current Windows user's DPAPI, never a plaintext config backup."""
    if os.name != 'nt':
        raise RuntimeError('Encrypted backups require Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'DSH plugin host backup', None, None, None, 1, ctypes.byref(dest))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(dest.data, dest.size)
    finally:
        kernel.LocalFree(dest.data)

@serialized
def snapshot(config, label='manual'):
    profile = Path(config['home']) / 'profiles/desktop'
    before = profile_hashes(profile)
    before_inventory=inventory(profile)
    if before['package.json'] is None:
        raise RuntimeError('Profile package.json is missing; no snapshot written')
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, digest in before.items():
            if digest is not None:
                z.writestr(name, (profile/name).read_bytes())
    if before != profile_hashes(profile) or before_inventory!=inventory(profile):
        raise RuntimeError('Profile changed during backup; retry after edits settle')
    sid = dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    target = STATE/'snapshots'/sid
    target.mkdir(parents=True)
    encrypted = dpapi(payload.getvalue())
    (target/'profile.dpapi').write_bytes(encrypted)
    # Verify decryptability and file hashes before committing metadata.
    with zipfile.ZipFile(io.BytesIO(dpapi(encrypted, True))) as z:
        for name in z.namelist():
            if hashlib.sha256(z.read(name)).hexdigest() != before[name]:
                raise RuntimeError('Backup verification failed')
    meta = {'id':sid, 'at':now(), 'label':label, 'profile':str(profile), 'hashes':before, 'inventory':before_inventory,
            'scope':'profile configuration only; no credentials, sessions, or node_modules',
            'encrypted_sha256':hashlib.sha256(encrypted).hexdigest()}
    write_json(target/'snapshot.json', meta)
    return meta

def powershell(script):
    result = subprocess.run([powershell_executable(), '-NoProfile', '-NonInteractive',
        '-Command', script], capture_output=True, encoding='utf-8', errors='replace',
        creationflags=NO_WINDOW, timeout=25)
    if result.returncode:
        raise RuntimeError('PowerShell inspection failed')
    return result.stdout.strip()

def running_hosts():
    # Restrict process inspection to DSH; return paths rather than command lines.
    raw = powershell("$p=@(Get-CimInstance Win32_Process -Filter \"Name='DeepSeek Harness.exe'\" | "
        "ForEach-Object { $s=$_.CommandLine; if($s -match 'dsh-desktop-host') { "
        "$m=[regex]::Match($s,'(?:\"([^\"]*profiles[\\\\/]desktop)\"|([^\\s\"]*profiles[\\\\/]desktop))'); "
        "[pscustomobject]@{pid=$_.ProcessId;exe=$_.ExecutablePath;profile=($m.Groups[1].Value+$m.Groups[2].Value)} "
        "} }); ConvertTo-Json -InputObject $p -Compress")
    return json.loads(raw or '[]')

def probe(exe, profile):
    exe = Path(exe)
    env = os.environ.copy()
    env['ELECTRON_RUN_AS_NODE'] = '1'
    result = subprocess.run([str(exe), '--expose-internals', str(ROOT/'probe.mjs'),
        str(exe.parent/'resources/app.asar/dsh'), str(profile)], env=env,
        capture_output=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW, timeout=35)
    # Ignore unrelated native runtime noise; only our JSON frame is accepted.
    frames = [line for line in result.stdout.splitlines() if line.startswith('{')]
    if not frames:
        raise RuntimeError('Runtime did not return a supported probe result')
    data = json.loads(frames[-1])
    if result.returncode or 'error' in data:
        raise RuntimeError(data.get('error', 'Runtime inspection failed'))
    data['exe'] = str(exe)
    return data

def crash_evidence(home):
    logs = Path(home)/'electron/logs'
    matches = sorted(logs.glob('crash-*.log'), key=lambda p:p.stat().st_mtime, reverse=True) if logs.exists() else []
    if not matches:
        return None
    path = matches[0]
    # Only recognized failure labels are persisted, never raw diagnostic contents.
    text = path.read_text(encoding='utf-8', errors='replace')
    pending = [{'plugin':m[0], 'service':m[1]} for m in re.findall(
        r'^([@\w./-]+): pending \(waiting for service: ([\w-]+)\)', text, re.M)]
    return {'at':dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
            'filename':path.name, 'pending':list({(x['plugin'],x['service']):x for x in pending}.values()),
            'historical':True}

def evaluate(config, inspect_running=True):
    profile = Path(config['home'])/'profiles/desktop'
    report = {'at':now(), 'profile':str(profile), 'runtimes':[], 'running':[],
              'profile_mismatch':False, 'crash':crash_evidence(config['home'])}
    for exe in dict.fromkeys([config['current_exe'], config['fallback_exe']]):
        try:
            report['runtimes'].append(probe(exe, profile))
        except Exception as e:
            report['runtimes'].append({'exe':exe, 'error':str(e), 'plugins':[]})
    if inspect_running:
        report['running'] = running_hosts()
        report['profile_mismatch'] = any(os.path.normcase(x['profile']) != os.path.normcase(str(profile)) for x in report['running'])
    for runtime in report['runtimes']:
        runtime['blockers'] = [p['name'] for p in runtime['plugins']
            if p['status'] != 'metadata-ok' and p.get('enabled') is not False]
        runtime['eligible_for_trial'] = not runtime.get('error') and not runtime['blockers']
    pending=pending_plugin_changes(config)
    report['pending_plugins']=pending
    for runtime in report['runtimes']:
        for plugin in runtime['plugins']:
            if plugin['name'] in pending:plugin['pending_enabled']=pending[plugin['name']]
    write_json(STATE/'report.json', report)
    render_report(report)
    return report

def pending_plugin_changes(config):
    path=STATE/'pending-plugins.json'
    if not path.exists():return {}
    saved=json.loads(path.read_text(encoding='utf-8'))
    profile=str(Path(config['home'])/'profiles/desktop')
    if os.path.normcase(saved.get('profile',''))!=os.path.normcase(profile):
        raise RuntimeError('待应用的插件开关属于其他配置目录，请先核对托管配置。')
    changes=saved.get('plugins',{})
    if not isinstance(changes,dict) or any(type(value) is not bool for value in changes.values()):
        raise RuntimeError('待应用的插件开关记录无效，配置未改动。')
    return changes

def _save_pending_plugins(config,changes):
    write_json(STATE/'pending-plugins.json',{'profile':str(Path(config['home'])/'profiles/desktop'),
        'plugins':changes,'at':now()})

def _toggle_runtime(config,report,exe=None):
    if exe:
        selected=next((r for r in report['runtimes'] if os.path.normcase(r['exe'])==os.path.normcase(exe)),None)
        if selected is None or selected.get('error'):raise RuntimeError('所选版本检查未完成，插件配置未改动。')
        return selected
    profile=os.path.normcase(str(Path(config['home'])/'profiles/desktop'))
    running=[p for p in report['running'] if os.path.normcase(p['profile'])==profile]
    if len(running)==1:
        matched=next((r for r in report['runtimes'] if os.path.normcase(r['exe'])==os.path.normcase(running[0]['exe']) and not r.get('error')),None)
        if matched:return matched
    preference=os.path.normcase(config.get('preferred_exe',''))
    candidates=sorted(report['runtimes'],key=lambda r:os.path.normcase(r['exe'])!=preference)
    selected=next((r for r in candidates if r['eligible_for_trial']),None)
    selected=selected or next((r for r in candidates if not r.get('error')),None)
    if selected is None:raise RuntimeError('没有能够读取插件配置的托管版本，请先完成版本检查。')
    return selected

def _validate_plugin_changes(runtime,changes):
    plugins={p['name']:p for p in runtime['plugins']}
    for name,enabled in changes.items():
        plugin=plugins.get(name)
        if plugin is None or name.startswith('@deepseek-ai/'):
            raise RuntimeError('只能调整托管列表中的第三方插件。')
        if plugin.get('toggle_supported') is False:
            raise RuntimeError(plugin.get('toggle_reason') or '此插件没有可独立调整的加载条目。')
        if enabled and plugin['status'] not in ('metadata-ok','dependency-blocked'):
            raise RuntimeError('所选插件在 '+runtime.get('runtime','当前版本')+' 上未通过声明检查，未启用。')
    desired={name:changes.get(name,p.get('enabled') is not False) for name,p in plugins.items()}
    dependencies={}
    for name,plugin in plugins.items():
        requirements=[]
        for dependency in plugin.get('declaredDependencies',[]):
            if not isinstance(dependency,str):continue
            if dependency in plugins or not dependency.startswith('@deepseek-ai/'):
                requirements.append([dependency])
        for service in plugin.get('needs',[]):
            providers=[n for n,p in plugins.items() if service in p.get('provides',[])]
            if providers:requirements.append(providers)
        dependencies[name]=requirements
    def available(name,seen=frozenset()):
        if name not in plugins or name in seen or not desired[name] or plugins[name]['status'] not in ('metadata-ok','dependency-blocked'):
            return False
        return all(any(available(provider,seen|{name}) for provider in group) for group in dependencies[name])
    for name,requirements in dependencies.items():
        if not desired[name]:continue
        for providers in requirements:
            affected=name in changes and changes[name] or any(p in changes for p in providers)
            if not affected:continue
            if not any(available(p) for p in providers):
                raise RuntimeError('插件 '+name+' 依赖未启用或不兼容的插件：'+', '.join(providers)+'。请先调整依赖插件。')

def _prepare_plugin_patch(config,runtime,changes):
    exe=Path(runtime['exe'])
    env=os.environ.copy();env['ELECTRON_RUN_AS_NODE']='1'
    result=subprocess.run([str(exe),'--expose-internals',str(ROOT/'toggle-patch.mjs'),
        str(exe.parent/'resources/app.asar/dsh'),str(Path(config['home'])/'profiles/desktop')],
        input=json.dumps(changes),env=env,capture_output=True,encoding='utf-8',errors='replace',
        creationflags=NO_WINDOW,timeout=35)
    frames=[line for line in result.stdout.splitlines() if line.startswith('{')]
    data=json.loads(frames[-1]) if frames else {}
    if result.returncode or data.get('error') or 'content_base64' not in data:
        raise RuntimeError('无法安全调整此插件的加载条目，配置未改动。'+(' ('+data['error']+')' if data.get('error') else ''))
    return data

def _apply_plugin_changes(config,runtime,changes):
    if not changes:return {'status':'unchanged','plugins':{},'restart_required':False}
    if running_hosts():raise RuntimeError('请先正常退出 DSH，再应用插件开关。不会中断现有任务。')
    _validate_plugin_changes(runtime,changes)
    profile=Path(config['home'])/'profiles/desktop'
    path=profile/'cordis.patch.yml'
    before=profile_hashes(profile)
    installed=inventory(profile)
    plan=_prepare_plugin_patch(config,runtime,changes)
    candidate=base64.b64decode(plan['content_base64'],validate=True)
    if before!=profile_hashes(profile) or installed!=inventory(profile) or fingerprint(path)!=plan['original_sha256']:
        raise RuntimeError('检查期间插件配置发生变化，请刷新后重试。')
    original=path.read_bytes() if path.exists() else None
    saved=snapshot(config,'before-plugin-toggle')
    if running_hosts() or before!=profile_hashes(profile) or installed!=inventory(profile):
        raise RuntimeError('应用前运行状态或配置已变化，插件开关未写入。')
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    wrote=False
    try:
        temp.write_bytes(candidate);os.replace(temp,path);wrote=True
        checked=probe(runtime['exe'],profile)
        by_name={p['name']:p for p in checked['plugins']}
        if any(by_name.get(name,{}).get('enabled') is not enabled for name,enabled in changes.items()):
            raise RuntimeError('加载器未确认所选开关状态。')
        _validate_plugin_changes(checked,changes)
        if fingerprint(path)!=hashlib.sha256(candidate).hexdigest() or installed!=inventory(profile):
            raise RuntimeError('验证期间插件配置发生变化。')
    except Exception:
        if wrote:
            if path.read_bytes()!=candidate:
                raise RuntimeError('插件配置被同时修改；已保留并行修改，请从操作前快照核对。')
            if original is None:path.unlink()
            else:
                temp.write_bytes(original);os.replace(temp,path)
        raise
    finally:
        if temp.exists():temp.unlink()
    return {'status':'applied','plugins':changes,'restart_required':False,'checked_runtime':runtime.get('runtime'),
        'checked_exe':runtime['exe'],'snapshot':saved['id'],'entry_ids':plan['entry_ids'],'functionality':'unverified'}

@serialized
def set_plugin_enabled(config,plugin_name,enabled):
    """Queue while DSH runs; otherwise apply only verified, backed-up disabled flags."""
    if type(enabled) is not bool:raise ValueError('插件开关必须为布尔值。')
    report=evaluate(config)
    runtime=_toggle_runtime(config,report)
    plugin=next((p for p in runtime['plugins'] if p['name']==plugin_name),None)
    if plugin is None:raise RuntimeError('未找到所选插件。')
    changes=dict(pending_plugin_changes(config))
    if plugin.get('enabled') is enabled:changes.pop(plugin_name,None)
    else:changes[plugin_name]=enabled
    _validate_plugin_changes(runtime,changes)
    # Prepare validates ownership and the composed flags without writing the profile.
    if changes:_prepare_plugin_patch(config,runtime,changes)
    if running_hosts():
        _save_pending_plugins(config,changes)
        return {'status':'queued' if changes else 'unchanged','plugin':plugin_name,'enabled':plugin.get('enabled'),
            'pending_enabled':changes.get(plugin_name),'restart_required':bool(changes),
            'checked_runtime':runtime.get('runtime'),'checked_exe':runtime['exe'],'pending_plugins':changes}
    result=_apply_plugin_changes(config,runtime,changes)
    _save_pending_plugins(config,{})
    return {**result,'plugin':plugin_name,'enabled':enabled}

@serialized
def apply_pending_plugins(config,exe=None):
    changes=pending_plugin_changes(config)
    if not changes:return {'status':'unchanged','plugins':{},'restart_required':False}
    if running_hosts():raise RuntimeError('请正常退出 DSH 后再应用待重启的插件开关。')
    report=evaluate(config)
    runtime=_toggle_runtime(config,report,exe)
    result=_apply_plugin_changes(config,runtime,changes)
    _save_pending_plugins(config,{})
    return result

def render_report(report):
    e = lambda x: html.escape(str(x))
    sections=[]
    for r in report['runtimes']:
        rows=[]
        for p in r['plugins']:
            detail = '; '.join(p.get('peers',{}).keys())
            if p.get('blockedBy'):
                detail = '; '.join(x['plugin'] + ' → ' + ', '.join(x['services']) for x in p['blockedBy'])
            rows.append('<tr><td>'+e(p['name'])+'</td><td>'+e(p.get('version','—'))+'</td><td>'+
                e(LABELS[p['status']] + ('（原配置已禁用）' if p.get('enabled') is False else ''))+'</td><td>'+e(detail)+'</td></tr>')
        sections.append(f"<h2>DSH {e(r.get('runtime','未知版本'))}</h2><p>{e(r.get('error') or str(len(r['blockers']))+' 个启动前阻断项')}</p>"
            '<table><thead><tr><th>插件</th><th>版本</th><th>检查结果</th><th>依赖说明</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>')
    crash=report.get('crash')
    history = e(json.dumps(crash, ensure_ascii=False, indent=2)) if crash else '暂无'
    body='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DSH 插件托管</title>
<style>body{font:15px/1.7 system-ui;margin:36px auto;max-width:1180px;padding:0 24px;color:#223046;background:#f4f6fa}h1{font-size:30px}table{background:white;border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;border-bottom:1px solid #e0e6ee;padding:10px;overflow-wrap:anywhere}th{background:#e7edf6}pre{white-space:pre-wrap}small{color:#526278}</style>
<h1>DSH 插件托管 · 本机版</h1><p>固定配置，保留插件；更新前检查，异常可回退。</p>'''
    body+=f"<p>检查时间：{e(report['at'])}<br>托管配置：{e(report['profile'])}<br>运行目录错位：{'是' if report['profile_mismatch'] else '未发现（未运行时不代表已验证）'}</p>"
    body+='<p><strong>元数据检查通过不等于功能兼容。</strong>本报告没有执行插件工具、模型请求或 Office 操作；依赖提示来自静态声明，历史崩溃另列。</p>'
    body+=''.join(sections)+'<h2>最近历史故障</h2><pre>'+history+'</pre></html>'
    (STATE/'report.html').write_text(body, encoding='utf-8')

def launch(config, exe):
    apply_pending_plugins(config,exe)
    report = evaluate(config)
    selected = next(r for r in report['runtimes'] if os.path.normcase(r['exe'])==os.path.normcase(exe))
    if not selected['eligible_for_trial']:
        raise RuntimeError('启动前检查未通过。已保留插件和设置，请查看报告；没有强行加载。')
    if running_hosts():
        raise RuntimeError('请先在 DSH 中正常退出，再启动托管版本。不会强制结束现有任务。')
    saved = snapshot(config, 'before-launch')
    env = os.environ.copy()
    env.pop('ELECTRON_RUN_AS_NODE',None)
    env['DSH_HOME']=config['home']
    env.update(config.get('launch_env',{}))
    subprocess.Popen([exe, '--user-data-dir='+str(Path(config['home'])/'electron')],
        env=env, cwd=str(Path(exe).parent), creationflags=NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    write_json(STATE/'last-launch.json', {'at':now(), 'exe':exe, 'snapshot':saved['id'], 'status':'started-not-verified'})
    return {'launched':exe, 'snapshot':saved['id'], 'status':'started-not-verified'}

@serialized
def save_preferred_version(config, exe):
    """Merge the choice without overwriting settings edited while checks were running."""
    latest=load_config()
    if any(latest.get(key)!=config.get(key) for key in ('home','current_exe','fallback_exe','launch_env')):
        raise RuntimeError('托管路径或启动配置已变化，请刷新后重新选择版本。')
    latest['preferred_exe']=exe
    write_json(ROOT/'local.json',latest)

def switch_version(config, exe):
    """Persist a checked choice; leave existing DSH tasks for the user to close normally."""
    selected_exe=next((path for path in (config['current_exe'],config['fallback_exe'])
        if os.path.normcase(path)==os.path.normcase(str(exe))),None)
    if selected_exe is None:
        raise ValueError('只能选择托管列表中的 DSH 版本。')
    if not running_hosts():apply_pending_plugins(config,selected_exe)
    report=evaluate(config)
    selected=next(r for r in report['runtimes']
        if os.path.normcase(r['exe'])==os.path.normcase(selected_exe))
    if not selected['eligible_for_trial']:
        raise RuntimeError('所选版本未通过启动前检查，默认版本未改动。请先解决报告中的阻断项。')
    save_preferred_version(config,selected_exe)
    result={'selected':selected_exe,'preferred_exe':selected_exe,'runtime':selected.get('runtime')}
    hosts=running_hosts()
    if hosts:
        profile=os.path.normcase(str(Path(config['home'])/'profiles/desktop'))
        same=len(hosts)==1 and os.path.normcase(hosts[0]['profile'])==profile and \
            os.path.normcase(hosts[0]['exe'])==os.path.normcase(selected_exe)
        return {**result,'status':'reused' if same else 'needs-exit'}
    try:
        return {**result,**launch(config,selected_exe)}
    except Exception as e:
        raise RuntimeError('默认版本已保存，但启动未完成：'+str(e)) from e

@serialized
def restore(config, sid):
    """Explicit, configuration-only rollback. Reject active processes and snapshot tampering."""
    if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{6}', sid):
        raise ValueError('Invalid snapshot id')
    if running_hosts():
        raise RuntimeError('请先正常退出 DSH，才能恢复配置。')
    pending=pending_plugin_changes(config)
    folder=STATE/'snapshots'/sid
    meta=json.loads((folder/'snapshot.json').read_text(encoding='utf-8'))
    profile=Path(config['home'])/'profiles/desktop'
    if os.path.normcase(meta['profile']) != os.path.normcase(str(profile)):
        raise RuntimeError('Snapshot belongs to a different profile')
    if meta.get('inventory') is None or inventory(profile)!=meta['inventory']:
        raise RuntimeError('插件安装版本与快照不同；未覆盖配置。此版本不会偷偷重装插件。')
    encrypted=(folder/'profile.dpapi').read_bytes()
    if hashlib.sha256(encrypted).hexdigest()!=meta['encrypted_sha256']:
        raise RuntimeError('Backup integrity mismatch')
    with zipfile.ZipFile(io.BytesIO(dpapi(encrypted,True))) as z:
        payload={n:z.read(n) for n in z.namelist()}
    if set(payload) != {n for n,h in meta['hashes'].items() if h is not None} or not set(payload)<=set(CONFIG_FILES):
        raise RuntimeError('Snapshot file list mismatch')
    for name,data in payload.items():
        if hashlib.sha256(data).hexdigest()!=meta['hashes'][name]:
            raise RuntimeError('Snapshot content mismatch')
    # Keep recovery limited to a coherent same-file-set snapshot. Never silently delete new config.
    if {n for n,h in profile_hashes(profile).items() if h is not None} != set(payload):
        raise RuntimeError('配置文件集合已变化；请人工合并，未覆盖或删除文件。')
    snapshot(config, 'before-restore')
    originals={n:(profile/n).read_bytes() for n in payload}
    try:
        for name,data in payload.items():
            temp=profile/(name+'.plugin-host.tmp')
            temp.write_bytes(data)
            os.replace(temp, profile/name)
        if profile_hashes(profile)!=meta['hashes']:
            raise RuntimeError('Restore verification failed')
        if pending:_save_pending_plugins(config,{})
    except Exception:
        for name,data in originals.items():
            (profile/name).write_bytes(data)
        raise
    return {'restored':sid, 'scope':'configuration only; installed plugin versions unchanged',
        'canceled_pending_plugins':len(pending)}

def smart_launch(config):
    """Honor an eligible saved choice, otherwise gate the configured runtime fallback."""
    hosts=running_hosts()
    if not hosts:apply_pending_plugins(config)
    profile=os.path.normcase(str(Path(config['home'])/'profiles/desktop'))
    env=os.environ.copy();env.pop('ELECTRON_RUN_AS_NODE',None)
    env['DSH_HOME']=config['home'];env.update(config.get('launch_env',{}))
    if hosts:
        if len(hosts)!=1 or os.path.normcase(hosts[0]['profile'])!=profile:
            raise RuntimeError('发现其他配置的 DSH 正在运行。请先正常退出；托管不会中断它。')
    preference=os.path.normcase(config.get('preferred_exe',''))
    chosen=None
    if not hosts or (preference and os.path.normcase(hosts[0]['exe'])!=preference):
        report=evaluate(config)
        candidates=sorted(report['runtimes'],key=lambda r:os.path.normcase(r['exe'])!=preference)
        chosen=next((r for r in candidates if r['eligible_for_trial']),None)
        if chosen is None:
            raise RuntimeError('新版和保留版本均未通过启动前检查；配置未改动，请查看报告。')
    if hosts:
        if chosen and os.path.normcase(hosts[0]['exe'])!=os.path.normcase(chosen['exe']):
            return {'status':'needs-exit','selected':chosen['exe'],'preferred_exe':config['preferred_exe']}
        subprocess.Popen([hosts[0]['exe'],'--user-data-dir='+str(Path(config['home'])/'electron')],
            env=env,creationflags=NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return {'status':'existing-managed-instance'}
    return launch(config,chosen['exe'])

def watch(config):
    """Small local watcher; only alerts on changed actionable evidence. Never upgrades DSH."""
    if os.name!='nt':
        raise RuntimeError('Windows only')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    mutex=kernel.CreateMutexW(None,False,'Local\\DSHPluginHostWatcher')
    if ctypes.get_last_error()==183:
        return
    last=None
    last_release=None
    write_json(STATE/'watcher.json', {'pid':os.getpid(),'started':now()})
    while not (STATE/'stop-watcher').exists():
        try:
            cfg=load_config()
            exe=Path(cfg['current_exe'])
            release=[str(exe),exe.stat().st_mtime_ns,(exe.parent/'resources/app.asar').stat().st_mtime_ns]
            current=[release, profile_hashes(Path(cfg['home'])/'profiles/desktop'), inventory(Path(cfg['home'])/'profiles/desktop'), running_hosts(),crash_evidence(cfg['home'])]
            signature=json.dumps(current,sort_keys=True)
            if signature!=last:
                report=evaluate(cfg)
                # Keep an immutable checkpoint for each observed stable configuration.
                snapshot(cfg,'observed-state')
                if release!=last_release and (STATE/'install.json').exists():
                    # Rebind only this tool's previously managed shortcuts after an installer replaced them.
                    subprocess.run([powershell_executable(),'-NoProfile','-NonInteractive',
                        '-File',str(ROOT/'install.ps1'),'-Action','Refresh'],capture_output=True,creationflags=NO_WINDOW,timeout=20,check=True)
                    last_release=release
                actionable=report['profile_mismatch'] or bool(report['runtimes'][0].get('error')) or bool(report['runtimes'][0]['blockers'])
                # New recognized crashes after a managed launch are actionable; historical logs stay historical.
                launched=STATE/'last-launch.json'
                launch_info=json.loads(launched.read_text(encoding='utf-8')) if launched.exists() else {}
                fresh_crash=report.get('crash') if report.get('crash') and report['crash']['at']>launch_info.get('at',now()) else None
                actionable=actionable or fresh_crash is not None
                notice=json.dumps([report['profile_mismatch'],report['runtimes'][0].get('runtime'),
                    report['runtimes'][0].get('error'),report['runtimes'][0]['blockers'],fresh_crash],sort_keys=True)
                notice_path=STATE/'last-notice.json'
                old=json.loads(notice_path.read_text(encoding='utf-8')) if notice_path.exists() else None
                if actionable and old!=notice:
                    write_json(notice_path,notice)
                    subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'ui.py'),'--alert'],creationflags=NO_WINDOW)
                elif not actionable and old is not None:
                    write_json(notice_path,None)
                last=signature
            write_json(STATE/'watcher.json',{'pid':os.getpid(),'checked':now(),'status':'watching'})
        except Exception as e:
            write_json(STATE/'watcher.json',{'pid':os.getpid(),'checked':now(),'status':'error','error':str(e)})
            if last!='watcher-error':
                subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(ROOT/'ui.py'),'--alert'],creationflags=NO_WINDOW)
                last='watcher-error'
        time.sleep(20)
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle(mutex)

def main():
    parser=argparse.ArgumentParser(description='DSH 插件托管（Windows 本机版）')
    parser.add_argument('action',choices=['check','snapshot','launch','fallback','restore','watch'])
    parser.add_argument('--snapshot-id')
    args=parser.parse_args()
    cfg=load_config()
    if args.action=='check':
        report=evaluate(cfg)
        result={'report':str(STATE/'report.html'), 'profile_mismatch':report['profile_mismatch'],
                'runtimes':[{k:r.get(k) for k in ('runtime','error','blockers','eligible_for_trial')} for r in report['runtimes']]}
    elif args.action=='snapshot': result=snapshot(cfg)
    elif args.action in ('launch','fallback'): result=launch(cfg,cfg['current_exe' if args.action=='launch' else 'fallback_exe'])
    elif args.action=='restore': result=restore(cfg,args.snapshot_id or '')
    else: watch(cfg); return
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try: main()
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False)); sys.exit(2)
