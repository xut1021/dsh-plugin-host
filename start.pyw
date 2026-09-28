import subprocess
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox
import host

try:
    # Start once per Windows session; watch() owns its own named mutex.
    if not (host.STATE/'stop-watcher').exists():
        subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(host.ROOT/'host.py'),'watch'],creationflags=host.NO_WINDOW)
    result = host.smart_launch(host.load_config())
    if result.get('status') == 'needs-exit':
        raise RuntimeError('默认版本已保存。请先正常退出当前 DSH，再从桌面入口打开以完成切换。')
except Exception as exc:
    root=tk.Tk();root.withdraw()
    messagebox.showwarning('DSH 插件托管',str(exc))
    subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(host.ROOT/'ui.py')],creationflags=host.NO_WINDOW)
    root.destroy()
