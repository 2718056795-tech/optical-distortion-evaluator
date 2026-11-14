"""Small native startup window; usable before Qt and the runtime are unpacked."""
import ctypes as C
from ctypes import wintypes as W
import os
import math
import struct
import threading
import time


class StartupSplash:
    def __init__(self, image):
        self.image = image
        self.progress = .02
        self._display_progress = .02
        self._last_frame = time.perf_counter()
        self._animation_frames = 0
        self._max_progress_step = 0.0
        self.hwnd = None
        self.error = None
        self.shown_at = None
        self.started_at = time.perf_counter()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='startup-splash', daemon=True)

    def start(self):
        self._thread.start()
        self._ready.wait(.8)
        return self

    def update(self, progress):
        self.progress = max(self.progress, min(.97, progress))

    def _advance_progress(self):
        now = time.perf_counter()
        dt = min(.032, max(0, now - self._last_frame))
        self._last_frame = now
        gap = max(0, self.progress - self._display_progress)
        step = min(gap, 1.25 * dt, gap * (1 - math.exp(-dt / .16)))
        self._display_progress += step
        self._animation_frames += 1
        self._max_progress_step = max(self._max_progress_step, step)

    def close(self):
        self._stop.set()
        if self.hwnd:
            C.windll.user32.PostMessageW(W.HWND(self.hwnd), 0x0010, 0, 0)
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def stats(self):
        return {'shown': self.shown_at is not None,
                'shown_after_hook_seconds': (round(self.shown_at - self.started_at, 3)
                                             if self.shown_at is not None else None),
                'runtime_ready_seconds': round(time.perf_counter() - self.started_at, 3),
                'closed': not self._thread.is_alive(), 'error': self.error,
                'animated_frames': self._animation_frames,
                'max_progress_step': round(self._max_progress_step, 5)}

    def _run(self):
        try:
            self._window_loop()
        except Exception as exc:
            self.error = repr(exc)
        finally:
            self.hwnd = None
            self._ready.set()

    def _window_loop(self):
        user = C.WinDLL('user32', use_last_error=True)
        gdi = C.WinDLL('gdi32', use_last_error=True)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        callback = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

        class WindowClass(C.Structure):
            _fields_ = [('style', W.UINT), ('proc', callback), ('cls_extra', C.c_int),
                        ('wnd_extra', C.c_int), ('instance', W.HINSTANCE), ('icon', W.HANDLE),
                        ('cursor', W.HANDLE), ('background', W.HBRUSH),
                        ('menu_name', W.LPCWSTR), ('class_name', W.LPCWSTR)]

        class PaintStruct(C.Structure):
            _fields_ = [('hdc', W.HDC), ('erase', W.BOOL), ('rect', W.RECT),
                        ('restore', W.BOOL), ('inc_update', W.BOOL), ('reserved', C.c_byte * 32)]

        class MonitorInfo(C.Structure):
            _fields_ = [('size', W.DWORD), ('monitor', W.RECT), ('work', W.RECT), ('flags', W.DWORD)]

        def api(lib, name, result, *args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, list(args)
            return fn

        module = api(kernel, 'GetModuleHandleW', W.HMODULE, W.LPCWSTR)(None)
        register = api(user, 'RegisterClassW', W.ATOM, C.POINTER(WindowClass))
        unregister = api(user, 'UnregisterClassW', W.BOOL, W.LPCWSTR, W.HINSTANCE)
        create = api(user, 'CreateWindowExW', W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                     C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p)
        default = api(user, 'DefWindowProcW', C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        begin = api(user, 'BeginPaint', W.HDC, W.HWND, C.POINTER(PaintStruct))
        end = api(user, 'EndPaint', W.BOOL, W.HWND, C.POINTER(PaintStruct))
        destroy = api(user, 'DestroyWindow', W.BOOL, W.HWND)
        load_image = api(user, 'LoadImageW', W.HANDLE, W.HINSTANCE, W.LPCWSTR, W.UINT,
                         C.c_int, C.c_int, W.UINT)
        make_dc = api(gdi, 'CreateCompatibleDC', W.HDC, W.HDC)
        select = api(gdi, 'SelectObject', W.HANDLE, W.HDC, W.HANDLE)
        delete = api(gdi, 'DeleteObject', W.BOOL, W.HANDLE)
        delete_dc = api(gdi, 'DeleteDC', W.BOOL, W.HDC)
        make_bitmap = api(gdi, 'CreateCompatibleBitmap', W.HBITMAP, W.HDC, C.c_int, C.c_int)
        copy_frame = api(gdi, 'BitBlt', W.BOOL, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
                         W.HDC, C.c_int, C.c_int, W.DWORD)
        fill_region = api(gdi, 'FillRgn', W.BOOL, W.HDC, W.HRGN, W.HBRUSH)
        stretch_mode = api(gdi, 'SetStretchBltMode', C.c_int, W.HDC, C.c_int)
        blit = api(gdi, 'StretchBlt', W.BOOL, W.HDC, C.c_int, C.c_int, C.c_int, C.c_int,
                   W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.DWORD)
        brush = api(gdi, 'CreateSolidBrush', W.HBRUSH, W.DWORD)
        fill = api(user, 'FillRect', C.c_int, W.HDC, C.POINTER(W.RECT), W.HBRUSH)
        region = api(gdi, 'CreateRoundRectRgn', W.HRGN, C.c_int, C.c_int, C.c_int,
                     C.c_int, C.c_int, C.c_int)
        set_region = api(user, 'SetWindowRgn', C.c_int, W.HWND, W.HRGN, W.BOOL)
        invalidate = api(user, 'InvalidateRect', W.BOOL, W.HWND, C.c_void_p, W.BOOL)
        set_timer = api(user, 'SetTimer', C.c_size_t, W.HWND, C.c_size_t, W.UINT, C.c_void_p)
        kill_timer = api(user, 'KillTimer', W.BOOL, W.HWND, C.c_size_t)
        get_message = api(user, 'GetMessageW', C.c_int, C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
        translate = api(user, 'TranslateMessage', W.BOOL, C.POINTER(W.MSG))
        dispatch = api(user, 'DispatchMessageW', C.c_ssize_t, C.POINTER(W.MSG))
        api(user, 'ShowWindow', W.BOOL, W.HWND, C.c_int)
        api(user, 'UpdateWindow', W.BOOL, W.HWND)
        api(user, 'GetCursorPos', W.BOOL, C.POINTER(W.POINT))
        api(user, 'MonitorFromPoint', W.HANDLE, W.POINT, W.DWORD)
        api(user, 'GetMonitorInfoW', W.BOOL, W.HANDLE, C.POINTER(MonitorInfo))
        api(user, 'PostQuitMessage', None, C.c_int)

        bitmap = load_image(None, os.path.abspath(self.image), 0, 0, 0, 0x2010)
        if not bitmap:
            raise C.WinError(C.get_last_error())
        with open(self.image, 'rb') as stream:
            stream.seek(18)
            iw, ih = struct.unpack('<ii', stream.read(8))
        memdc = make_dc(None)
        old_bitmap = select(memdc, bitmap)
        blue = brush(0x00FF7A00)  # Windows COLORREF: #007aff
        width, height = 560, 244
        if hasattr(user, 'GetDpiForSystem'):
            scale = user.GetDpiForSystem() / 96
            width, height = round(width * scale), round(height * scale)

        @callback
        def proc(hwnd, message, wp, lp):
            if message == 0x0014:  # WM_ERASEBKGND; paint the complete image instead
                return 1
            if message == 0x000F:  # WM_PAINT
                paint = PaintStruct()
                hdc = begin(hwnd, C.byref(paint))
                frame_dc, frame_bitmap, old_frame = None, None, None
                try:
                    # Compose off-screen so the static card never flashes between frames.
                    frame_dc = make_dc(hdc)
                    frame_bitmap = make_bitmap(hdc, width, height)
                    if not frame_dc or not frame_bitmap:
                        return 0
                    old_frame = select(frame_dc, frame_bitmap)
                    stretch_mode(frame_dc, 4)
                    blit(frame_dc, 0, 0, width, height, memdc, 0, 0, iw, abs(ih), 0x00CC0020)
                    left, top = round(40 * width / 560), round(176 * height / 244)
                    right = left + max(1, round(480 * width / 560 * self._display_progress))
                    bar_height = max(3, round(5 * height / 244))
                    shape = region(left, top, right + 1, top + bar_height + 1, bar_height, bar_height)
                    fill_region(frame_dc, shape, blue)
                    delete(shape)
                    copy_frame(hdc, 0, 0, width, height, frame_dc, 0, 0, 0x00CC0020)
                finally:
                    if old_frame:
                        select(frame_dc, old_frame)
                    if frame_bitmap:
                        delete(frame_bitmap)
                    if frame_dc:
                        delete_dc(frame_dc)
                    end(hwnd, C.byref(paint))
                return 0
            if message == 0x0113:  # WM_TIMER
                if self._stop.is_set():
                    destroy(hwnd)
                else:
                    self._advance_progress()
                    invalidate(hwnd, None, False)
                return 0
            if message == 0x0010:  # WM_CLOSE
                destroy(hwnd)
                return 0
            if message == 0x0002:  # WM_DESTROY
                kill_timer(hwnd, 1)
                user.PostQuitMessage(0)
                return 0
            return default(hwnd, message, wp, lp)

        name = 'OpticalDistortionStartup_' + str(os.getpid())
        wc = WindowClass(0, proc, 0, 0, module, None, None, None, None, name)
        atom = register(C.byref(wc))
        if not atom:
            raise C.WinError(C.get_last_error())
        hwnd = None
        try:
            point = W.POINT()
            user.GetCursorPos(C.byref(point))
            monitor = user.MonitorFromPoint(point, 2)
            info = MonitorInfo()
            info.size = C.sizeof(info)
            if not user.GetMonitorInfoW(monitor, C.byref(info)):
                raise C.WinError(C.get_last_error())
            area = info.work
            x = area.left + (area.right - area.left - width) // 2
            y = area.top + (area.bottom - area.top - height) // 2
            hwnd = create(0x08000080, name, '光机镜头畸变评估工具', 0x80000000,
                          x, y, width, height, None, None, module, None)
            if not hwnd:
                raise C.WinError(C.get_last_error())
            self.hwnd = hwnd
            corner = max(12, round(36 * width / 560))
            shape = region(0, 0, width + 1, height + 1, corner, corner)
            if not set_region(hwnd, shape, True):
                delete(shape)
            self._last_frame = time.perf_counter()
            set_timer(hwnd, 1, 16, None)
            user.ShowWindow(hwnd, 4)  # no focus stealing while the user waits
            user.UpdateWindow(hwnd)
            self.shown_at = time.perf_counter()
            self._ready.set()
            if self._stop.is_set():
                destroy(hwnd)
            message = W.MSG()
            while get_message(C.byref(message), None, 0, 0) > 0:
                translate(C.byref(message))
                dispatch(C.byref(message))
        finally:
            if hwnd:
                destroy(hwnd)
            unregister(name, module)
            select(memdc, old_bitmap)
            delete_dc(memdc)
            delete(bitmap)
            delete(blue)


def close_startup():
    import builtins
    started = getattr(builtins, '_optical_startup_started', None)
    if started is not None and not hasattr(builtins, '_optical_main_ready_seconds'):
        builtins._optical_main_ready_seconds = round(time.perf_counter() - started, 4)
    splash = getattr(builtins, '_optical_startup_splash', None)
    if splash is not None:
        splash.close()

