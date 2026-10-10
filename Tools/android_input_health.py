"""Nonvisual input-lifecycle qualification for the pinned owned CE client.

NuoActivityGame.processTouch checks NuoView.Renderer.isInitialized. Android
foreground/activity state alone can precede native resume completion. This
reads the client's existing lifecycle log, not images or frame-rate counters.
"""
import re
import time
import json


def activate_owned_ldplayer(executable, *, process_id=None):
    """Restore/focus one path-qualified owned emulator; no pixels or recording.

    Android's focused-window name does not imply its Java view has focus when
    LDPlayer is minimized/backgrounded. This host action is only readiness:
    callers must still verify guest view focus and actual command consumption.
    """
    import ctypes
    from ctypes import wintypes
    import os
    from pathlib import Path
    import sys
    if sys.platform != 'win32':
        raise RuntimeError('LDPlayer focus qualification requires Windows')
    expected=os.path.normcase(str(Path(executable).resolve(strict=True)))
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    user.GetForegroundWindow.restype=wintypes.HWND
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype=wintypes.DWORD
    for name in ('IsWindowVisible','IsIconic','SetForegroundWindow','BringWindowToTop'):
        getattr(user,name).argtypes=[wintypes.HWND]
    user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    candidates=[]
    @callback_type
    def visit(hwnd,_):
        name=ctypes.create_unicode_buffer(128)
        user.GetClassNameW(hwnd,name,len(name))
        if name.value!='LDPlayerMainFrame':return True
        pid=wintypes.DWORD();thread=user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        handle=kernel.OpenProcess(0x1000,False,pid.value)
        if not handle:return True
        try:
            path=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(path))
            if (kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(length))
                    and os.path.normcase(path.value)==expected
                    and (process_id is None or pid.value == process_id)):
                candidates.append((hwnd,pid.value,thread))
        finally:kernel.CloseHandle(handle)
        return True
    user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    if not user.EnumWindows(visit,0) or len(candidates)!=1:
        raise RuntimeError('owned LDPlayer window absent or ambiguous; no focus action')
    hwnd,pid,target_thread=candidates[0]
    record={'host_wall':time.time(),'pid':pid,'hwnd':hwnd,'executable':expected,
            'before_minimized':bool(user.IsIconic(hwnd)),
            'before_foreground':user.GetForegroundWindow()}
    own_thread=kernel.GetCurrentThreadId()
    foreground_thread=user.GetWindowThreadProcessId(record['before_foreground'],None)
    attached=[]
    try:
        for thread in set((foreground_thread,target_thread))-{0,own_thread}:
            ok = user.AttachThreadInput(own_thread,thread,True)
            record.setdefault('attach', []).append({'thread':thread, 'ok':bool(ok),
                                                    'error':ctypes.get_last_error() if not ok else 0})
            if ok:attached.append(thread)
        user.ShowWindow(hwnd,9)
        user.BringWindowToTop(hwnd)
        record['set_foreground_result'] = bool(user.SetForegroundWindow(hwnd))
    finally:
        for thread in attached:user.AttachThreadInput(own_thread,thread,False)
    record.update(after_minimized=bool(user.IsIconic(hwnd)),
                  after_foreground=user.GetForegroundWindow())
    if record['after_minimized'] or record['after_foreground']!=hwnd:
        raise RuntimeError('owned emulator foreground activation did not qualify: '+json.dumps(record))
    return record

ROW = re.compile(r'^\s*(\d+\.\d+)\s+(\d+)\s+\d+\s+[VDIWEF]\s+NUO\s*:\s*(.*)$')
MARKERS = ('Resume - Pre', 'Resume - Post', 'Suspend - Pre', 'Suspend - Post')


def require_owned_foreground(activation):
    """Read-only check of the already qualified hwnd/pid; never refocus."""
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.IsIconic.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD()
    hwnd = activation['hwnd']
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    result = {'host_wall': time.time(), 'hwnd': hwnd, 'pid': pid.value,
              'foreground': user.GetForegroundWindow(), 'minimized': bool(user.IsIconic(hwnd))}
    if result['foreground'] != hwnd or result['pid'] != activation['pid'] or result['minimized']:
        raise ValueError('entry: host foreground ownership lost; no further gestures: ' + json.dumps(result))
    return result


def native_input_lifecycle(logcat, pid, *, after_guest_wall=None):
    events = []
    for line in logcat.splitlines():
        match = ROW.match(line)
        if not match or int(match[2]) != pid:
            continue
        marker = next((m for m in MARKERS if 'RenderEvent - '+m in match[3]), None)
        if marker:
            events.append({'guest_wall':float(match[1]), 'marker':marker, 'line':line.strip()})
    latest = max(events, key=lambda r:r['guest_wall']) if events else None
    ready = bool(latest and latest['marker'] == 'Resume - Post' and
                 (after_guest_wall is None or latest['guest_wall'] > after_guest_wall))
    return {'pid':pid, 'ready':ready, 'latest':latest, 'after_guest_wall':after_guest_wall,
            'scope':'native lifecycle readiness, not successful touch delivery'}


def wait_native_input_ready(adb, *, timeout=30, after_guest_wall=None):
    if not 0 < timeout <= 60:
        raise ValueError('input readiness wait must be bounded to60seconds')
    pid_text = adb.shell('pidof com.superevilmegacorp.game')
    if not pid_text.isdecimal():
        raise ValueError('owned client process absent or ambiguous')
    pid = int(pid_text)
    deadline, observations = time.monotonic()+timeout, []
    while time.monotonic() < deadline:
        if adb.shell('pidof com.superevilmegacorp.game') != pid_text:
            raise RuntimeError('owned client process changed during input readiness check')
        text = adb.shell('logcat -d -v epoch -t 2000 -s NUO:D')
        state = native_input_lifecycle(text, pid, after_guest_wall=after_guest_wall)
        observations.append({'host_wall':time.time(), **state})
        if state['ready']:
            return {'ready':True, 'observations':observations}
        time.sleep(.25)
    return {'ready':False, 'observations':observations}


def launch_readiness(pid_text, activities, logcat, *, after_guest_wall):
    """Pre-attach Android state plus initialized-only native resume anchor.

    Pinned NuoView.Renderer.executeState's Resume branch tests isInitialized
    before both Resume markers (owned smali lines 147..209). The init marker
    precedes startup and is deliberately NOT an initialization-complete proof.
    """
    pid = int(pid_text) if pid_text.isdecimal() else None
    lifecycle = native_input_lifecycle(logcat, pid, after_guest_wall=after_guest_wall)
    component = 'com.superevilmegacorp.game/com.superevilmegacorp.nuogameentry.NuoActivityGame'
    blocks = re.split(r'\* Hist #\d+:', activities)[1:]
    resumed = bool(pid and any(component in block.splitlines()[0] and 'state=RESUMED' in block
        and re.search(r'app=ProcessRecord\{[^\n]*\b' + str(pid) + r':com\.superevilmegacorp\.game/', block)
        for block in blocks))
    init_starts = [float(match[1]) for line in logcat.splitlines()
                   if (match := ROW.match(line)) and int(match[2]) == pid
                   and 'logFunctionName(init)' in match[3] and 'NuoView$Renderer::onSurfaceChanged' in match[3]]
    latest_init = max(init_starts, default=None)
    initialized = (True if lifecycle['ready'] and
                   (latest_init is None or latest_init < lifecycle['latest']['guest_wall']) else None)
    return {'pid': pid, 'activity_resumed': resumed, 'initialized': initialized,
            'initialized_basis': 'pinned isInitialized-gated Resume - Post, not init-start log',
            'latest_init_start': latest_init, 'lifecycle': lifecycle, 'ready': bool(resumed and initialized)}


def wait_launch_ready(adb, *, after_guest_wall, timeout=60, record=lambda row: None):
    """No attach/input: require three ready samples at least one second apart."""
    if not 0 < timeout <= 90 or not isinstance(after_guest_wall, (int, float)):
        raise ValueError('launch readiness requires bounded wait and guest launch timestamp')
    deadline, observations, stable = time.monotonic()+timeout, [], []
    while time.monotonic() < deadline:
        pid_command = 'pidof com.superevilmegacorp.game || test $? -eq 1'
        pid = adb.shell(pid_command)
        activities = adb.shell('dumpsys activity activities')
        logcat = adb.shell('logcat -d -v epoch -s NUO:D ActivityManager:I lowmemorykiller:I frida:I')
        state = launch_readiness(pid, activities, logcat, after_guest_wall=after_guest_wall)
        state.update(host_wall=time.time(), monotonic=time.monotonic(), activities=activities, logcat=logcat)
        if adb.shell(pid_command) != pid:
            state.update(ready=False, pid_changed_during_sample=True)
        observations.append(state)
        record(state)
        if state['ready']:
            if stable and stable[-1]['pid'] != state['pid']:
                stable = []
            stable.append(state)
            if len(stable) >= 3:
                return {'ready': True, 'pid': state['pid'], 'observations': observations}
        else:
            stable = []
        time.sleep(1)
    return {'ready': False, 'observations': observations}
