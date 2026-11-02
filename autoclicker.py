# -*- coding: utf-8 -*-
"""连点器 —— 单文件绿色版（Python 3 + tkinter，无需任何第三方库）

功能
----
* 三种点击位置：跟随鼠标当前位置 / 固定坐标 / 多点轮巡（在多个坐标间轮流点击）
* 多点轮巡：列表里增删、拖动顺序（上移/下移）、按顺序或随机轮流点
* 可设置：点击间隔(毫秒)、点击次数、左/右/中键、按下时长、启动延时
* 后台点击模式：把点击消息直接投递给窗口，完全不移动系统光标，
  因此连点某块屏上的程序时，另一块显示器可以照常使用鼠标键盘
* 高级随机化：间隔按百分比浮动、坐标随机偏移（降低被识别成脚本的概率）
* 全局热键（窗口在后台甚至最小化时也有效）：
      F6  开始 / 停止
      F7  拾取当前鼠标坐标 / 在轮巡模式下添加坐标
* 设置自动保存到同目录 autoclicker_config.json

用法
----
双击 启动连点器.bat，或命令行:  pythonw autoclicker.py
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox, ttk

# ---------------------------------------------------------------- Win32 基础

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

ULONG_PTR = ctypes.c_size_t
INPUT_MOUSE = 0

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

VK_F6 = 0x75
VK_F7 = 0x76

BUTTONS = {
    "左键": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "右键": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "中键": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# 后台点击：直接把消息投递给窗口，不移动系统光标
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010
BM_CLICK = 0x00F5

POST_BUTTONS = {
    "左键": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
    "右键": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
    "中键": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = wintypes.SHORT
user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
user32.GetSystemMetrics.restype = ctypes.c_int
kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
user32.WindowFromPoint.argtypes = (wintypes.POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
user32.ScreenToClient.restype = wintypes.BOOL
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.IsWindow.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def _lparam(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def _is_own_window(hwnd: int) -> bool:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == kernel32.GetCurrentProcessId()


def window_at(x: int, y: int) -> int:
    """返回该屏幕坐标处最上层的窗口句柄（0 表示没有）。"""
    return user32.WindowFromPoint(wintypes.POINT(int(x), int(y))) or 0


def screen_to_client(hwnd: int, x: int, y: int) -> tuple[int, int] | None:
    pt = wintypes.POINT(int(x), int(y))
    if not user32.ScreenToClient(hwnd, ctypes.byref(pt)):
        return None
    return pt.x, pt.y


def post_click(hwnd: int, cx: int, cy: int, button: str, press_s: float) -> bool:
    """后台点击：把点击投递给窗口，系统光标完全不动。"""
    if button == "左键" and "BUTTON" in _class_name(hwnd).upper():
        # 标准按钮在按下/抬起时会检查真实光标位置，只有 BM_CLICK 才认
        ok = bool(user32.PostMessageW(hwnd, BM_CLICK, 0, 0))
        time.sleep(press_s)
        return ok
    down, up, mk = POST_BUTTONS[button]
    lp = _lparam(cx, cy)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    ok = bool(user32.PostMessageW(hwnd, down, mk, lp))
    time.sleep(press_s)
    ok = bool(user32.PostMessageW(hwnd, up, 0, lp)) and ok
    return ok


def enable_dpi_awareness() -> None:
    """按物理像素工作，避免高分屏下坐标偏移。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _send(flags: int) -> bool:
    inp = INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(0, 0, 0, flags, 0, 0)))
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1


def move_to(x: int, y: int) -> None:
    """把系统光标移动到屏幕坐标 (x, y)。"""
    _send_absolute(x, y, MOUSEEVENTF_MOVE)


def _send_absolute(x: int, y: int, flags: int) -> bool:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    ax = int(round((x - vx) * 65535 / max(1, vw - 1)))
    ay = int(round((y - vy) * 65535 / max(1, vh - 1)))
    inp = INPUT(
        INPUT_MOUSE,
        _INPUTUNION(
            mi=MOUSEINPUT(
                ax,
                ay,
                0,
                flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                0,
                0,
            )
        ),
    )
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1


# ---------------------------------------------------------------- 点击引擎


class ClickEngine:
    """在后台线程里按设定节奏点击，随时可被 F6 打断。"""

    def __init__(self) -> None:
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self.clicks = 0
        self.state = "idle"  # idle | countdown | running
        self.countdown_end = 0.0
        self.error: str | None = None
        self.background = False

    # -- 状态 --------------------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, cfg: dict) -> bool:
        if self.is_running():
            return False
        self.clicks = 0
        self.error = None
        self.countdown_end = 0.0
        self.background = bool(cfg.get("background"))
        self._stop_evt.clear()
        self.state = "countdown" if cfg["delay"] > 0 else "running"
        self._thread = threading.Thread(target=self._run, args=(cfg,), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_evt.set()

    def join(self, timeout: float = 1.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # -- 主循环 ------------------------------------------------------------
    def _run(self, cfg: dict) -> None:
        down_flag, up_flag = BUTTONS[cfg["button"]]
        button = cfg["button"]
        interval = cfg["interval"]
        jitter = cfg["jitter"]
        offset = cfg["offset"]
        anchor = cfg["anchor"]
        points = cfg.get("points") or []
        shuffle = bool(cfg.get("random_order"))
        max_clicks = cfg["count"]
        press = cfg["press"]
        background = bool(cfg.get("background"))
        # 后台模式：先把每个坐标对应的窗口解析出来，之后即使被别的窗口盖住也能点
        bg_hwnds: dict[int, int] = {}
        if background:
            if points:
                for i, (px, py) in enumerate(points):
                    bg_hwnds[i] = window_at(px, py)
            elif anchor is not None:
                bg_hwnds[-1] = window_at(*anchor)
        try:
            if cfg["delay"] > 0:
                self.state = "countdown"
                self.countdown_end = time.perf_counter() + cfg["delay"]
                if self._stop_evt.wait(cfg["delay"]):
                    return
            self.state = "running"
            next_t = time.perf_counter()
            idx = 0
            fail_streak = 0
            while not self._stop_evt.is_set():
                if max_clicks and self.clicks >= max_clicks:
                    break
                press_s = max(0.001, min(press, interval * 0.6))

                # 轮巡点 > 固定坐标 > 跟随鼠标
                target = None
                key = -1
                if points:
                    if shuffle:
                        key = random.randrange(len(points))
                    else:
                        key = idx % len(points)
                        idx += 1
                    target = points[key]
                elif anchor is not None:
                    target = anchor

                if target is not None:
                    tx, ty = target
                    if offset:
                        tx += random.randint(-offset, offset)
                        ty += random.randint(-offset, offset)

                clicked = False
                if background:
                    if target is None:
                        tx, ty = get_cursor_pos()

                    hwnd = bg_hwnds.get(key, 0) if target is not None else 0
                    if not hwnd or not user32.IsWindow(hwnd):
                        hwnd = window_at(tx, ty)
                        if target is not None:
                            bg_hwnds[key] = hwnd
                    if hwnd and _is_own_window(hwnd):
                        fail_streak += 1
                        if fail_streak >= 3:
                            self.error = "坐标落在连点器自己的窗口上，请把窗口移开再试"
                            break
                        continue
                    client = screen_to_client(hwnd, tx, ty) if hwnd else None
                    if client:
                        clicked = post_click(hwnd, client[0], client[1], button, press_s)
                else:
                    if target is not None:
                        cx, cy = get_cursor_pos()
                        if abs(cx - tx) > 1 or abs(cy - ty) > 1:
                            _send_absolute(tx, ty, MOUSEEVENTF_MOVE)
                            time.sleep(0.004)
                    # 跟随鼠标模式不发送 MOUSEEVENTF_MOVE，避免把光标"拉回"起点，
                    # 否则用户一边移动鼠标一边点击时会被抢指针。
                    _send(down_flag)
                    time.sleep(press_s)
                    _send(up_flag)
                    clicked = True

                if clicked:
                    fail_streak = 0
                    self.clicks += 1
                else:
                    fail_streak += 1
                    if fail_streak >= 3:
                        self.error = "后台点击失败：该坐标处没有可用窗口"
                        break

                if max_clicks and self.clicks >= max_clicks:
                    break
                if self._stop_evt.is_set():
                    break

                wait = interval
                if jitter:
                    wait *= 1.0 + random.uniform(-jitter, jitter)
                wait = max(0.001, wait)
                next_t += wait
                while True:
                    remain = next_t - time.perf_counter()
                    if remain <= 0:
                        break
                    if self._stop_evt.wait(min(remain, 0.01)):
                        break
        except Exception as exc:  # pragma: no cover - 兜底
            self.error = str(exc)
        finally:
            self.state = "idle"


# ---------------------------------------------------------------- 图形界面

APP_TITLE = "连点器"
CONFIG_NAME = "autoclicker_config.json"
MUTEX_NAME = "Local\\AutoClicker_DSH_SingleInstance"
FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")

COLOR_BG = "#f5f6f8"
COLOR_CARD = "#ffffff"
COLOR_TEXT = "#1f2329"
COLOR_MUTED = "#8a9099"
COLOR_OK = "#2ea44f"
COLOR_RUN = "#e8590c"
COLOR_ACCENT = "#2f6fed"


def app_dir() -> str:
    """程序所在目录：源码运行时是脚本目录，打包成 exe 后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """优先用打包进 exe 的资源，其次用程序目录里的同名文件。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        bundled = os.path.join(base, name)
        if os.path.exists(bundled):
            return bundled
    return os.path.join(app_dir(), name)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.engine = ClickEngine()
        self.hotkey_queue: queue.Queue[str] = queue.Queue()
        self._hk_stop = threading.Event()
        self._cfg_path = os.path.join(app_dir(), CONFIG_NAME)
        self._was_running = False
        self._shown_error: str | None = None

        self._build_ui()
        self._load_config()
        self._start_hotkeys()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tick()

    # -- 界面搭建 ----------------------------------------------------------
    def _build_ui(self) -> None:
        r = self.root
        r.title(APP_TITLE)
        r.configure(bg=COLOR_BG)
        r.resizable(False, False)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TLabelFrame", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("TLabelFrame.Label", font=FONT_BOLD, foreground="#394150")
        style.configure("TLabel", background=COLOR_CARD, foreground=COLOR_TEXT, font=FONT)
        style.configure("Muted.TLabel", foreground=COLOR_MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TRadiobutton", background=COLOR_CARD, font=FONT)
        style.configure("TCheckbutton", background=COLOR_BG, font=FONT)
        style.configure("Card.TCheckbutton", background=COLOR_CARD,
                        font=("Microsoft YaHei UI", 9))
        style.configure("TEntry", font=FONT)
        style.configure("TCombobox", font=FONT)

        outer = tk.Frame(r, bg=COLOR_BG, padx=14, pady=12)
        outer.pack(fill="both", expand=True)

        # 点击位置
        f_pos = ttk.LabelFrame(outer, text=" 点击位置 ", padding=(12, 8, 12, 10))
        f_pos.pack(fill="x", pady=(0, 10))
        self.var_mode = tk.StringVar(value="cursor")
        ttk.Radiobutton(
            f_pos, text="跟随鼠标当前位置", value="cursor", variable=self.var_mode,
            command=self._on_mode_change,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        row = tk.Frame(f_pos, bg=COLOR_CARD)
        row.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            row, text="固定坐标", value="fixed", variable=self.var_mode,
            command=self._on_mode_change,
        ).pack(side="left")
        ttk.Label(row, text="X").pack(side="left", padx=(14, 4))
        self.var_x = tk.StringVar(value="0")
        self.ent_x = ttk.Entry(row, textvariable=self.var_x, width=7, justify="center")
        self.ent_x.pack(side="left")
        ttk.Label(row, text="Y").pack(side="left", padx=(8, 4))
        self.var_y = tk.StringVar(value="0")
        self.ent_y = ttk.Entry(row, textvariable=self.var_y, width=7, justify="center")
        self.ent_y.pack(side="left")
        self.btn_pick = tk.Button(
            row, text="拾取 (F7)", command=self.pick_position,
            font=("Microsoft YaHei UI", 9), relief="flat", bd=0,
            bg="#e8eefc", fg=COLOR_ACCENT, activebackground="#d8e3fb",
            padx=10, pady=2, cursor="hand2",
        )
        self.btn_pick.pack(side="left", padx=(12, 0))

        ttk.Radiobutton(
            f_pos, text="多点轮巡（在几个坐标之间轮流点击）", value="multi",
            variable=self.var_mode, command=self._on_mode_change,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # 轮巡坐标（仅多点模式显示）
        self.f_multi = ttk.LabelFrame(outer, text=" 轮巡坐标 ", padding=(12, 8, 12, 10))
        self.points: list[tuple[int, int]] = []
        box = tk.Frame(self.f_multi, bg=COLOR_CARD)
        box.pack(fill="x")
        self.lst_points = tk.Listbox(
            box, height=5, font=("Consolas", 10), activestyle="none",
            selectmode="extended", bd=1, relief="solid", highlightthickness=0,
            bg="#ffffff", fg=COLOR_TEXT, selectbackground="#cfe0ff",
            selectforeground=COLOR_TEXT, exportselection=False,
        )
        self.lst_points.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.lst_points.yview)
        sb.pack(side="right", fill="y")
        self.lst_points.configure(yscrollcommand=sb.set)

        bar = tk.Frame(self.f_multi, bg=COLOR_CARD)
        bar.pack(fill="x", pady=(8, 0))
        self._multi_btn(bar, "添加当前坐标 (F7)", self.add_point, "#e8eefc", COLOR_ACCENT)
        self._multi_btn(bar, "删除选中", self.remove_points)
        self._multi_btn(bar, "清空", self.clear_points)
        self._multi_btn(bar, "上移", lambda: self.move_point(-1))
        self._multi_btn(bar, "下移", lambda: self.move_point(1))
        self.var_shuffle = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="随机顺序", variable=self.var_shuffle, style="Card.TCheckbutton",
        ).pack(side="right")

        # 参数
        self.f_par = f_par = ttk.LabelFrame(outer, text=" 参数 ", padding=(12, 8, 12, 10))
        f_par.pack(fill="x", pady=(0, 10))
        for c in (1, 3, 5):
            f_par.columnconfigure(c, weight=1)

        ttk.Label(f_par, text="间隔").grid(row=0, column=0, sticky="w")
        self.var_interval = tk.StringVar(value="100")
        ttk.Entry(f_par, textvariable=self.var_interval, width=8, justify="center").grid(
            row=0, column=1, padx=(6, 4), pady=4, sticky="w"
        )
        ttk.Label(f_par, text="毫秒").grid(row=0, column=2, sticky="w")
        ttk.Label(f_par, text="次数").grid(row=0, column=3, sticky="e", padx=(16, 0))
        self.var_count = tk.StringVar(value="0")
        ttk.Entry(f_par, textvariable=self.var_count, width=8, justify="center").grid(
            row=0, column=4, padx=(6, 4), pady=4, sticky="w"
        )
        ttk.Label(f_par, text="次（0=无限）", style="Muted.TLabel").grid(
            row=0, column=5, sticky="w"
        )

        ttk.Label(f_par, text="按键").grid(row=1, column=0, sticky="w")
        self.var_button = tk.StringVar(value="左键")
        ttk.Combobox(
            f_par, textvariable=self.var_button, values=list(BUTTONS),
            width=6, state="readonly", justify="center",
        ).grid(row=1, column=1, padx=(6, 4), pady=4, sticky="w")
        ttk.Label(f_par, text="按下时长").grid(row=1, column=3, sticky="e")
        self.var_press = tk.StringVar(value="20")
        ttk.Entry(f_par, textvariable=self.var_press, width=8, justify="center").grid(
            row=1, column=4, padx=(6, 4), pady=4, sticky="w"
        )
        ttk.Label(f_par, text="毫秒", style="Muted.TLabel").grid(row=1, column=5, sticky="w")

        ttk.Label(f_par, text="启动延时").grid(row=2, column=0, sticky="w")
        self.var_delay = tk.StringVar(value="0")
        ttk.Entry(f_par, textvariable=self.var_delay, width=8, justify="center").grid(
            row=2, column=1, padx=(6, 4), pady=4, sticky="w"
        )
        ttk.Label(f_par, text="秒（留时间切换窗口）", style="Muted.TLabel").grid(
            row=2, column=2, columnspan=4, sticky="w"
        )

        # 高级
        f_adv = ttk.LabelFrame(
            outer, text=" 高级 · 随机化 / 后台点击 ", padding=(12, 8, 12, 10)
        )
        f_adv.pack(fill="x", pady=(0, 10))
        ttk.Label(f_adv, text="间隔浮动").grid(row=0, column=0, sticky="w")
        self.var_jitter = tk.StringVar(value="0")
        ttk.Entry(f_adv, textvariable=self.var_jitter, width=6, justify="center").grid(
            row=0, column=1, padx=(6, 4), pady=4, sticky="w"
        )
        ttk.Label(f_adv, text="%", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Label(f_adv, text="位置偏移").grid(row=0, column=3, sticky="e", padx=(20, 0))
        self.var_offset = tk.StringVar(value="0")
        ttk.Entry(f_adv, textvariable=self.var_offset, width=6, justify="center").grid(
            row=0, column=4, padx=(6, 4), pady=4, sticky="w"
        )
        ttk.Label(f_adv, text="像素", style="Muted.TLabel").grid(row=0, column=5, sticky="w")

        self.var_bg = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f_adv, text="后台点击（不移动鼠标，另一个显示器可正常使用）",
            variable=self.var_bg, style="Card.TCheckbutton",
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(
            f_adv, text="不移动光标，直接把点击投递给窗口；目标别被其他窗口挡住，游戏/部分程序不认",
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=6, sticky="w")

        # 操作区
        f_btn = tk.Frame(outer, bg=COLOR_BG)
        f_btn.pack(fill="x", pady=(2, 8))
        self.btn_start = tk.Button(
            f_btn, text="开始  (F6)", command=self.toggle, font=FONT_BOLD,
            bg=COLOR_ACCENT, fg="white", activebackground="#2559c9",
            activeforeground="white", relief="flat", bd=0, padx=18, pady=7,
            cursor="hand2",
        )
        self.btn_start.pack(side="left")
        self.btn_reset = tk.Button(
            f_btn, text="复位", command=self.reset, font=FONT,
            bg="#eceef2", fg="#394150", activebackground="#e0e3e9",
            relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
        )
        self.btn_reset.pack(side="left", padx=(8, 0))
        self.var_top = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f_btn, text="窗口置顶", variable=self.var_top, command=self._apply_topmost
        ).pack(side="right")

        # 状态栏
        f_status = tk.Frame(outer, bg="#eef0f4", highlightthickness=0)
        f_status.pack(fill="x")
        self.lbl_dot = tk.Label(
            f_status, text="●", font=("Microsoft YaHei UI", 11), bg="#eef0f4",
            fg=COLOR_MUTED,
        )
        self.lbl_dot.pack(side="left", padx=(10, 2), pady=6)
        self.lbl_state = tk.Label(
            f_status, text="待机", font=FONT_BOLD, bg="#eef0f4", fg="#394150",
        )
        self.lbl_state.pack(side="left", pady=6)
        self.lbl_count = tk.Label(
            f_status, text="已点击 0", font=FONT, bg="#eef0f4", fg="#394150",
        )
        self.lbl_count.pack(side="right", padx=(0, 10), pady=6)
        self.lbl_hint = tk.Label(
            f_status, text="F6 开始/停止 · F7 拾取/添加坐标", font=("Microsoft YaHei UI", 9),
            bg="#eef0f4", fg=COLOR_MUTED,
        )
        self.lbl_hint.pack(side="right", padx=(0, 16), pady=6)

        self._on_mode_change()
        self._apply_topmost()

    # -- 交互 --------------------------------------------------------------
    def _on_mode_change(self) -> None:
        mode = self.var_mode.get()
        fixed = mode == "fixed"
        multi = mode == "multi"
        state = "normal" if fixed else "disabled"
        for w in (self.ent_x, self.ent_y):
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        try:
            if fixed:
                self.btn_pick.configure(
                    state="normal", bg="#e8eefc", fg=COLOR_ACCENT, cursor="hand2"
                )
            else:
                self.btn_pick.configure(
                    state="disabled", bg="#f1f2f5", fg="#b3b8c1",
                    disabledforeground="#b3b8c1", cursor="arrow",
                )
        except tk.TclError:
            pass

        if multi:
            self.f_multi.pack(fill="x", pady=(0, 10), before=self.f_par)
        else:
            self.f_multi.pack_forget()
        try:
            self.root.geometry("")  # 让窗口跟随内容重新自适应高度
        except tk.TclError:
            pass

        try:
            self.lbl_hint.configure(
                text="F6 开始/停止 · F7 添加坐标"
                if multi else "F6 开始/停止 · F7 拾取/添加坐标"
            )
        except (AttributeError, tk.TclError):
            pass

        if fixed and self.var_x.get() in ("", "0") and self.var_y.get() in ("", "0"):
            x, y = get_cursor_pos()
            self.var_x.set(str(x))
            self.var_y.set(str(y))

    def _apply_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", bool(self.var_top.get()))
        except tk.TclError:
            pass

    def pick_position(self) -> None:
        x, y = get_cursor_pos()
        self.var_x.set(str(x))
        self.var_y.set(str(y))
        self.var_mode.set("fixed")
        self._on_mode_change()

    # -- 轮巡坐标 ----------------------------------------------------------
    def _multi_btn(self, parent, text, cmd, bg="#eceef2", fg="#394150"):
        btn = tk.Button(
            parent, text=text, command=cmd, font=("Microsoft YaHei UI", 9),
            relief="flat", bd=0, bg=bg, fg=fg, activebackground="#dfe3ea",
            activeforeground=fg, padx=10, pady=3, cursor="hand2",
        )
        btn.pack(side="left", padx=(0, 6))
        return btn

    def _refresh_points(self) -> None:
        self.lst_points.delete(0, "end")
        for i, (x, y) in enumerate(self.points, 1):
            self.lst_points.insert("end", f"{i:>2}.   X={x:<6} Y={y}")

    def add_point(self, x=None, y=None) -> None:
        if x is None or y is None:
            x, y = get_cursor_pos()
        self.points.append((int(x), int(y)))
        self._refresh_points()
        self.lst_points.selection_clear(0, "end")
        self.lst_points.selection_set("end")
        self.lst_points.see("end")

    def remove_points(self) -> None:
        sel = sorted(self.lst_points.curselection(), reverse=True)
        if not sel:
            messagebox.showinfo(APP_TITLE, "先在列表里选中要删的坐标（可按住 Ctrl 多选）。")
            return
        for i in sel:
            if 0 <= i < len(self.points):
                del self.points[i]
        self._refresh_points()

    def clear_points(self) -> None:
        if not self.points:
            return
        if messagebox.askyesno(APP_TITLE, "确定清空全部轮巡坐标？"):
            self.points.clear()
            self._refresh_points()

    def move_point(self, delta: int) -> None:
        sel = list(self.lst_points.curselection())
        if len(sel) != 1:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < len(self.points):
            self.points[i], self.points[j] = self.points[j], self.points[i]
            self._refresh_points()
            self.lst_points.selection_clear(0, "end")
            self.lst_points.selection_set(j)
            self.lst_points.see(j)

    def toggle(self) -> None:
        if self.engine.is_running():
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        cfg = self._read_config()
        if cfg is None:
            return
        if cfg.get("background"):
            targets = cfg["points"] or ([cfg["anchor"]] if cfg["anchor"] else [])
            if targets and not any(window_at(x, y) for x, y in targets):
                messagebox.showwarning(
                    APP_TITLE,
                    "后台点击：这些坐标处现在没有窗口。\n\n"
                    "请先打开目标窗口（不要最小化），再点开始；\n"
                    "后台模式不移动光标，所以必须能找到该位置的窗口。",
                )
                return
        if self.engine.start(cfg):
            self._save_config()
            self._set_running_look(True)

    def stop(self) -> None:
        self.engine.stop()

    def reset(self) -> None:
        self.engine.stop()
        self.engine.clicks = 0
        self._update_status()

    def _set_running_look(self, running: bool) -> None:
        if running:
            self.btn_start.configure(
                text="停止  (F6)", bg="#e8590c", activebackground="#c94a08"
            )
        else:
            self.btn_start.configure(
                text="开始  (F6)", bg=COLOR_ACCENT, activebackground="#2559c9"
            )

    # -- 配置读写 ----------------------------------------------------------
    def _read_config(self) -> dict | None:
        def num(var: tk.StringVar, name: str, lo: float, hi: float) -> float:
            raw = var.get().strip()
            try:
                val = float(raw)
            except ValueError:
                raise ValueError(f"「{name}」请填写数字")
            if not (lo <= val <= hi):
                raise ValueError(f"「{name}」需要在 {lo:g} ~ {hi:g} 之间")
            return val

        try:
            interval = num(self.var_interval, "间隔", 1, 600000) / 1000.0
            count = int(num(self.var_count, "次数", 0, 10_000_000))
            press = num(self.var_press, "按下时长", 1, 1000) / 1000.0
            delay = num(self.var_delay, "启动延时", 0, 600)
            jitter = num(self.var_jitter, "间隔浮动", 0, 95) / 100.0
            offset = int(num(self.var_offset, "位置偏移", 0, 200))
            anchor = None
            points: list[tuple[int, int]] = []
            mode = self.var_mode.get()
            if mode == "fixed":
                try:
                    ax = int(float(self.var_x.get().strip()))
                    ay = int(float(self.var_y.get().strip()))
                except ValueError:
                    raise ValueError("固定坐标需要填写数字")
                anchor = (ax, ay)
            elif mode == "multi":
                if not self.points:
                    raise ValueError(
                        "多点轮巡至少要有一个坐标：先点「添加当前坐标」或按 F7 录几个点。"
                    )
                points = list(self.points)
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return None
        return {
            "interval": interval,
            "count": count,
            "press": press,
            "delay": delay,
            "jitter": jitter,
            "offset": offset,
            "anchor": anchor,
            "points": points,
            "random_order": bool(self.var_shuffle.get()),
            "background": bool(self.var_bg.get()),
            "button": self.var_button.get() if self.var_button.get() in BUTTONS else "左键",
        }

    def _load_config(self) -> None:
        try:
            with open(self._cfg_path, "r", encoding="utf-8-sig") as fp:
                data = json.load(fp)
        except Exception:
            x, y = get_cursor_pos()
            self.var_x.set(str(x))
            self.var_y.set(str(y))
            return
        mapping = {
            "interval": (self.var_interval, 100),
            "count": (self.var_count, 0),
            "press": (self.var_press, 20),
            "delay": (self.var_delay, 0),
            "jitter": (self.var_jitter, 0),
            "offset": (self.var_offset, 0),
        }
        for key, (var, default) in mapping.items():
            val = data.get(key, default)
            var.set(str(val))
        self.var_mode.set(data.get("mode", "cursor"))
        self.var_button.set(data.get("button", "左键"))
        self.var_top.set(bool(data.get("topmost", True)))
        self.points = []
        for p in data.get("points") or []:
            try:
                self.points.append((int(p[0]), int(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
        self._refresh_points()
        self.var_shuffle.set(bool(data.get("random_order", False)))
        self.var_bg.set(bool(data.get("background", False)))
        ax = data.get("x")
        ay = data.get("y")
        if ax is not None and ay is not None:
            self.var_x.set(str(ax))
            self.var_y.set(str(ay))
        self._on_mode_change()
        self._apply_topmost()

    def _save_config(self) -> None:
        data = {
            "interval": self.var_interval.get(),
            "count": self.var_count.get(),
            "press": self.var_press.get(),
            "delay": self.var_delay.get(),
            "jitter": self.var_jitter.get(),
            "offset": self.var_offset.get(),
            "mode": self.var_mode.get(),
            "button": self.var_button.get(),
            "x": self.var_x.get(),
            "y": self.var_y.get(),
            "topmost": bool(self.var_top.get()),
            "points": [[x, y] for x, y in self.points],
            "random_order": bool(self.var_shuffle.get()),
            "background": bool(self.var_bg.get()),
        }
        try:
            with open(self._cfg_path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # -- 全局热键 ----------------------------------------------------------
    def _start_hotkeys(self) -> None:
        def loop() -> None:
            prev = {VK_F6: False, VK_F7: False}
            while not self._hk_stop.is_set():
                for vk, name in ((VK_F6, "toggle"), (VK_F7, "pick")):
                    down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                    if down and not prev[vk]:
                        self.hotkey_queue.put(name)
                    prev[vk] = down
                time.sleep(0.012)

        threading.Thread(target=loop, daemon=True).start()

    # -- UI 刷新 -----------------------------------------------------------
    def _tick(self) -> None:
        while True:
            try:
                action = self.hotkey_queue.get_nowait()
            except queue.Empty:
                break
            if action == "toggle":
                self.toggle()
            elif action == "pick":
                if self.var_mode.get() == "multi":
                    self.add_point()
                else:
                    self.pick_position()

        running = self.engine.is_running()
        if running != self._was_running:
            self._was_running = running
            self._set_running_look(running)
        if self.engine.error and self.engine.error != self._shown_error:
            self._shown_error = self.engine.error
            messagebox.showwarning(APP_TITLE, self.engine.error)
        self._update_status()
        self.root.after(80, self._tick)

    def _update_status(self) -> None:
        state = self.engine.state
        if state == "countdown":
            left = max(0.0, self.engine.countdown_end - time.perf_counter())
            text, color = f"{left:.1f} 秒后开始", COLOR_RUN
        elif state == "running":
            text = "运行中（后台·不动鼠标）" if self.engine.background else "运行中"
            color = COLOR_OK
        else:
            text, color = "待机", COLOR_MUTED
        if self.engine.error:
            text, color = "出错", "#d1242f"
        self.lbl_state.configure(text=text, fg="#394150")
        self.lbl_dot.configure(fg=color)
        self.lbl_count.configure(text=f"已点击 {self.engine.clicks}")

    # -- 退出 --------------------------------------------------------------
    def on_close(self) -> None:
        self._hk_stop.set()
        self.engine.stop()
        self.engine.join(0.5)
        self._save_config()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------- 入口


def _single_instance() -> bool:
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return False
    return True


def main() -> int:
    enable_dpi_awareness()
    if not _single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_TITLE, "连点器已经在运行了。")
        root.destroy()
        return 0

    try:
        winmm.timeBeginPeriod(1)  # 提高 sleep 精度
    except Exception:
        pass

    root = tk.Tk()
    root.configure(bg=COLOR_BG)
    for ico in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "AutoClicker", "clicker.ico"),
        resource_path("clicker.ico"),
        resource_path("连点器图标.ico"),
    ):
        if ico and os.path.exists(ico):
            try:
                root.iconbitmap(ico)
                break
            except tk.TclError:
                continue
    try:
        dpi = user32.GetDpiForSystem()
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
    App(root)
    try:
        root.mainloop()
    finally:
        try:
            winmm.timeEndPeriod(1)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
