#requires -Version 7.0
param([ValidateSet('Install','Refresh','Remove')][string]$Action='Install')
$ErrorActionPreference='Stop'
$configPath=Join-Path $PSScriptRoot 'local.json'
if(-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw '缺少 local.json。请先复制 local.example.json 为 local.json，并填写本机 DSH 路径。'
}
try {$cfg=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json}
catch {throw 'local.json 不是有效的 JSON，请检查格式和 Windows 路径转义。'}
$stateDir=Join-Path $PSScriptRoot 'state'
$record=Join-Path $stateDir 'install.json'
$desktop=[Environment]::GetFolderPath('Desktop')
$programs=[Environment]::GetFolderPath('Programs')
$startup=[Environment]::GetFolderPath('Startup')
$sh=New-Object -ComObject WScript.Shell

function Write-Link([string]$Path,[string]$Target,[string]$Arguments) {
    $s=$sh.CreateShortcut($Path)
    $s.TargetPath=$Target
    $s.Arguments=$Arguments
    $s.WorkingDirectory=$PSScriptRoot
    $s.Description='DSH 插件托管：固定配置、启动前检查、保留版本回退'
    $s.IconLocation="$($cfg.current_exe),0"
    $s.Save()
}
function Broadcast-Environment {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DshEnvironmentNotification {
 [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 public static extern IntPtr SendMessageTimeout(IntPtr h, uint m, UIntPtr w, string l, uint f, uint t, out UIntPtr r);
}
'@
    [UIntPtr]$result=[UIntPtr]::Zero
    [void][DshEnvironmentNotification]::SendMessageTimeout([IntPtr]0xffff,0x1a,[UIntPtr]::Zero,'Environment',2,100,[ref]$result)
}

if($Action -eq 'Remove') {
    if(-not (Test-Path -LiteralPath $record)){throw 'No installation record; nothing changed.'}
    $prior=Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
    Set-Content -LiteralPath (Join-Path $stateDir 'stop-watcher') -Value 'stop' -Encoding utf8
    foreach($link in $prior.links) {
        if(Test-Path -LiteralPath $link.path) {
            $s=$sh.CreateShortcut($link.path)
            if($s.Arguments -notlike "*$PSScriptRoot*"){Write-Warning "User changed shortcut; preserved: $($link.path)";continue}
        }
        if($link.backup){Copy-Item -LiteralPath $link.backup -Destination $link.path -Force}
        elseif(Test-Path -LiteralPath $link.path){Remove-Item -LiteralPath $link.path}
    }
    if([Environment]::GetEnvironmentVariable('DSH_HOME','User') -eq $cfg.home) {
        [Environment]::SetEnvironmentVariable('DSH_HOME',$prior.previousDshHome,'User')
        Broadcast-Environment
    }
    Write-Output 'Removed launch integration. Project and encrypted backups preserved.'
    exit
}

# Validate everything before changing shortcuts, installation records or DSH_HOME.
# WindowsApps python.exe is a Store alias, not a Python installation.
$pythonCommand=Get-Command python.exe -ErrorAction SilentlyContinue
$pythonArguments=@()
if(-not $pythonCommand -or $pythonCommand.Source -like '*\WindowsApps\*') {
    $pythonCommand=Get-Command py.exe -ErrorAction SilentlyContinue
    $pythonArguments=@('-3')
}
if(-not $pythonCommand){throw '未找到 Python。请安装包含 tkinter 和 pythonw.exe 的 Python 3.10+，并将 python.exe 或 py.exe 加入 PATH。'}
$runtimeText=& $pythonCommand.Source @pythonArguments -c 'import sys,json; print(json.dumps({"executable":sys.executable,"major":sys.version_info.major,"minor":sys.version_info.minor}))'
if($LASTEXITCODE -ne 0){throw '无法运行 Python，请检查 python.exe / py.exe 安装。'}
try {$runtime=$runtimeText | ConvertFrom-Json}
catch {throw 'Python 没有返回有效的解释器路径，请检查 PATH 中的 python.exe / py.exe。'}
if($runtime.major -ne 3 -or $runtime.minor -lt 10){throw '请使用 Python 3.10 或更新的 Python 3 版本。'}
$pythonPath=$runtime.executable
$pythonw=Join-Path (Split-Path $pythonPath) 'pythonw.exe'
if(-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw '当前 Python 没有 pythonw.exe，无法创建桌面入口。请安装完整的 Windows Python。'
}
$validationCode=@'
import sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'vendor'))
try:
    import tkinter, customtkinter
    import host
    host.load_config(check_paths=True)
    host.powershell_executable()
    for name in ('ui.py','start.pyw','probe.mjs','toggle-patch.mjs'):
        if not (root/name).is_file():
            raise RuntimeError('Project file missing: '+name)
except ImportError:
    print('Python dependencies missing. Run: python -m pip install --target vendor -r requirements.txt (tkinter requires the full Python installer).')
    sys.exit(2)
except Exception as exc:
    print(str(exc))
    sys.exit(2)
'@
$validation=& $pythonPath -X utf8 -c $validationCode $PSScriptRoot
if($LASTEXITCODE -ne 0){throw "安装前检查未通过；尚未改动快捷方式或 DSH_HOME。`n$validation"}

if($Action -eq 'Install' -and -not (Test-Path -LiteralPath $record)) {
    New-Item -ItemType Directory -Path (Join-Path $stateDir 'shortcut-backups') -Force | Out-Null
    $paths=@((Join-Path $desktop 'DeepSeek Harness.lnk'),(Join-Path $desktop 'DeepSeek Harness (2).lnk'),
        (Join-Path $programs 'DeepSeek Harness.lnk'),(Join-Path $desktop 'DSH 插件托管.lnk'),
        (Join-Path $startup 'DSH Plugin Host.lnk'))
    $links=@()
    foreach($path in $paths) {
        $backup=$null
        if(Test-Path -LiteralPath $path) {
            $backup=Join-Path $stateDir ('shortcut-backups/'+[Guid]::NewGuid().ToString()+'.lnk')
            Copy-Item -LiteralPath $path -Destination $backup
        }
        $links+=@{path=$path;backup=$backup}
    }
    @{installed=(Get-Date).ToString('o');previousDshHome=[Environment]::GetEnvironmentVariable('DSH_HOME','User');links=$links} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $record -Encoding utf8
}
if(-not (Test-Path -LiteralPath $record)){throw 'Install before Refresh.'}
$installed=Get-Content -LiteralPath $record -Raw | ConvertFrom-Json
foreach($link in $installed.links) {
    $name=Split-Path $link.path -Leaf
    # A refresh may repair an installer-owned DSH shortcut; leave unrelated custom edits alone.
    if($Action -eq 'Refresh' -and (Test-Path -LiteralPath $link.path)) {
        $existing=$sh.CreateShortcut($link.path)
        if($existing.Arguments -notlike "*$PSScriptRoot*" -and $existing.TargetPath -ne $cfg.current_exe){continue}
    }
    if($name -eq 'DSH 插件托管.lnk') {
        Write-Link $link.path $pythonw ('"'+(Join-Path $PSScriptRoot 'ui.py')+'"')
    } elseif($name -eq 'DSH Plugin Host.lnk') {
        Write-Link $link.path $pythonw ('"'+(Join-Path $PSScriptRoot 'host.py')+'" watch')
    } else {
        Write-Link $link.path $pythonw ('"'+(Join-Path $PSScriptRoot 'start.pyw')+'"')
    }
}
if($Action -eq 'Install') {
    # DSH's supported single-root mechanism also covers installer-created entry points.
    [Environment]::SetEnvironmentVariable('DSH_HOME',$cfg.home,'User')
    Broadcast-Environment
    $stopFile=Join-Path $stateDir 'stop-watcher'
    if(Test-Path -LiteralPath $stopFile){Remove-Item -LiteralPath $stopFile}
    Start-Process -FilePath $pythonw -ArgumentList ('"'+(Join-Path $PSScriptRoot 'host.py')+'" watch') -WindowStyle Hidden
}
Write-Output "DSH Plugin Host $Action complete. Profile: $($cfg.home)"
