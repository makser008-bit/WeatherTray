"""
WeatherTray - погода у віджеті біля системного трея Windows 11 (той самий рушій віджета, що в X11Battery).
Чистий ctypes (без pip-залежностей). Віджет - прозоре дочірнє вікно панелі завдань: піксельна
прозорість, шрифт Windows 11, власна підказка, відступ від трея, перетягування, закріплення,
вибір монітора, меню у стилі Windows 11. Місце визначається геолокацією (за IP) або вручну.
Дані погоди: Open-Meteo (без ключа API), пошук місць: OpenStreetMap (Nominatim).
"""
import ctypes, json, math, os, re, sys, threading, time, urllib.parse, urllib.request
from ctypes import wintypes as wt
import winreg

APP = "WeatherTray"
VERSION = "0.4.4"

def app_dir():
    base = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    return os.path.dirname(base)

def log_exc():
    """Пише помилки в weather_tray.log поруч з програмою (для діагностики)."""
    try:
        import traceback
        path = os.path.join(app_dir(), "weather_tray.log")
        if os.path.exists(path) and os.path.getsize(path) > 200000:
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
    except OSError:
        pass


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)

P = ctypes.c_void_p
LRESULT = ctypes.c_ssize_t

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
uxtheme = ctypes.WinDLL("uxtheme", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

class GUID(ctypes.Structure):
    _fields_ = [("D1", wt.DWORD), ("D2", wt.WORD), ("D3", wt.WORD), ("D4", ctypes.c_ubyte * 8)]

class SP_DID(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("Guid", GUID), ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]

class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
                ("InLen", wt.USHORT), ("OutLen", wt.USHORT), ("FeatLen", wt.USHORT),
                ("Reserved", wt.USHORT * 17), ("NumLinkNodes", wt.USHORT),
                ("NumInBtn", wt.USHORT), ("NumInVal", wt.USHORT), ("NumInIdx", wt.USHORT),
                ("NumOutBtn", wt.USHORT), ("NumOutVal", wt.USHORT), ("NumOutIdx", wt.USHORT),
                ("NumFeatBtn", wt.USHORT), ("NumFeatVal", wt.USHORT), ("NumFeatIdx", wt.USHORT)]

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", P), ("hIcon", P), ("hCursor", P),
                ("hbrBackground", P), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", P), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", P), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", P)]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", P), ("hbmColor", P)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

class TOOLINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("uFlags", wt.UINT), ("hwnd", P), ("uId", ctypes.c_size_t),
                ("rect", wt.RECT), ("hinst", P), ("lpszText", P), ("lParam", wt.LPARAM), ("lpReserved", P)]

class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("fMask", wt.UINT), ("fType", wt.UINT), ("fState", wt.UINT),
                ("wID", wt.UINT), ("hSubMenu", P), ("hbmpChecked", P), ("hbmpUnchecked", P),
                ("dwItemData", ctypes.c_size_t), ("dwTypeData", wt.LPWSTR), ("cch", wt.UINT),
                ("hbmpItem", P)]

class TEXTMETRICW(ctypes.Structure):
    _fields_ = [("tmHeight", wt.LONG), ("tmAscent", wt.LONG), ("tmDescent", wt.LONG),
                ("tmInternalLeading", wt.LONG), ("tmExternalLeading", wt.LONG),
                ("tmAveCharWidth", wt.LONG), ("tmMaxCharWidth", wt.LONG), ("tmWeight", wt.LONG),
                ("tmOverhang", wt.LONG), ("tmDigitizedAspectX", wt.LONG), ("tmDigitizedAspectY", wt.LONG),
                ("tmFirstChar", wt.WCHAR), ("tmLastChar", wt.WCHAR), ("tmDefaultChar", wt.WCHAR),
                ("tmBreakChar", wt.WCHAR), ("tmItalic", wt.BYTE), ("tmUnderlined", wt.BYTE),
                ("tmStruckOut", wt.BYTE), ("tmPitchAndFamily", wt.BYTE), ("tmCharSet", wt.BYTE)]

class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD), ("hwndTrack", P), ("dwHoverTime", wt.DWORD)]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]

MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, P, P, P, wt.LPARAM)

class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("dwICC", wt.DWORD)]

# ---------------- прототипи ----------------
k32.GetModuleHandleW.restype = P
k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
k32.CreateMutexW.restype = P
k32.CreateMutexW.argtypes = [P, wt.BOOL, wt.LPCWSTR]
k32.GetUserPreferredUILanguages.argtypes = [wt.DWORD, ctypes.POINTER(wt.ULONG), P, ctypes.POINTER(wt.ULONG)]
k32.GetUserDefaultLocaleName.argtypes = [wt.LPWSTR, ctypes.c_int]
INVALID = P(-1).value

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.restype = P
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, P, P, P, P]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), P, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostMessageW.argtypes = [P, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.SetTimer.argtypes = [P, ctypes.c_size_t, wt.UINT, P]
user32.CreatePopupMenu.restype = P
user32.AppendMenuW.argtypes = [P, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.argtypes = [P, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, P, P]
user32.DestroyMenu.argtypes = [P]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.SetForegroundWindow.argtypes = [P]
user32.DestroyIcon.argtypes = [P]
user32.DestroyWindow.argtypes = [P]
user32.GetDC.restype = P
user32.GetDC.argtypes = [P]
user32.ReleaseDC.argtypes = [P, P]
user32.FillRect.argtypes = [P, ctypes.POINTER(wt.RECT), P]
user32.DrawTextW.argtypes = [P, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT]
user32.CreateIconIndirect.restype = P
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.LoadCursorW.restype = P
user32.LoadCursorW.argtypes = [P, P]
gdi32.CreateCompatibleDC.restype = P
gdi32.CreateCompatibleDC.argtypes = [P]
gdi32.CreateCompatibleBitmap.restype = P
gdi32.CreateCompatibleBitmap.argtypes = [P, ctypes.c_int, ctypes.c_int]
gdi32.CreateBitmap.restype = P
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wt.UINT, wt.UINT, P]
gdi32.SelectObject.restype = P
gdi32.SelectObject.argtypes = [P, P]
gdi32.CreateSolidBrush.restype = P
gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
gdi32.DeleteObject.argtypes = [P]
gdi32.DeleteDC.argtypes = [P]
gdi32.SetTextColor.argtypes = [P, wt.DWORD]
gdi32.SetBkMode.argtypes = [P, ctypes.c_int]
gdi32.CreateFontW.restype = P
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
user32.FindWindowW.restype = P
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = P
user32.FindWindowExW.argtypes = [P, P, wt.LPCWSTR, wt.LPCWSTR]
user32.GetWindowRect.argtypes = [P, ctypes.POINTER(wt.RECT)]
user32.SetWindowPos.argtypes = [P, P, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.ShowWindow.argtypes = [P, ctypes.c_int]
user32.IsWindow.argtypes = [P]
user32.SetCapture.argtypes = [P]
user32.SendMessageW.restype = LRESULT
user32.SendMessageW.argtypes = [P, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.UpdateLayeredWindow.argtypes = [P, P, P, P, P, P, wt.DWORD, P, wt.DWORD]
gdi32.CreateDIBSection.restype = P
gdi32.CreateDIBSection.argtypes = [P, P, wt.UINT, P, P, wt.DWORD]
gdi32.GdiFlush.argtypes = []
gdi32.CreatePen.restype = P
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.GetStockObject.restype = P
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.MoveToEx.argtypes = [P, ctypes.c_int, ctypes.c_int, P]
gdi32.LineTo.argtypes = [P, ctypes.c_int, ctypes.c_int]
gdi32.RoundRect.argtypes = [P] + [ctypes.c_int] * 6
gdi32.Polygon.argtypes = [P, P, ctypes.c_int]
gdi32.GetTextExtentPoint32W.argtypes = [P, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.SIZE)]
gdi32.TextOutW.argtypes = [P, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int]
gdi32.GetTextFaceW.argtypes = [P, ctypes.c_int, wt.LPWSTR]
gdi32.GetTextMetricsW.argtypes = [P, ctypes.POINTER(TEXTMETRICW)]
user32.GetWindowTextW.argtypes = [P, wt.LPWSTR, ctypes.c_int]
user32.SetWindowTextW.argtypes = [P, wt.LPCWSTR]
user32.MessageBoxW.argtypes = [P, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
user32.AdjustWindowRectEx.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD]
user32.IsDialogMessageW.argtypes = [P, ctypes.POINTER(wt.MSG)]
user32.SetFocus.argtypes = [P]
user32.GetClientRect.argtypes = [P, ctypes.POINTER(wt.RECT)]
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
user32.IsWindowVisible.argtypes = [P]
gdi32.SetBkColor.argtypes = [P, wt.DWORD]
uxtheme.SetWindowTheme.argtypes = [P, wt.LPCWSTR, wt.LPCWSTR]
dwmapi.DwmSetWindowAttribute.argtypes = [P, wt.DWORD, P, wt.DWORD]
user32.InsertMenuItemW.argtypes = [P, wt.UINT, wt.BOOL, ctypes.POINTER(MENUITEMINFOW)]
user32.LoadImageW.restype = P
user32.LoadImageW.argtypes = [P, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetMenuItemCount.restype = ctypes.c_int
user32.GetMenuItemCount.argtypes = [P]
comctl32.InitCommonControlsEx.argtypes = [P]
user32.EnumDisplayMonitors.argtypes = [P, P, MONITORENUMPROC, wt.LPARAM]
user32.GetMonitorInfoW.argtypes = [P, P]
user32.MonitorFromWindow.restype = P
user32.MonitorFromWindow.argtypes = [P, wt.DWORD]
shell32.ShellExecuteW.restype = P
shell32.ShellExecuteW.argtypes = [P, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]
try:
    user32.GetDpiForWindow.restype = wt.UINT
    user32.GetDpiForWindow.argtypes = [P]
except AttributeError:
    pass


gdi32.Ellipse.argtypes = [P] + [ctypes.c_int] * 4

# ---------------- мови інтерфейсу (автовизначення мови Windows) ----------------
LANG_DIR = os.path.join(app_dir(), "lang")  # додаткові мови: lang/xx.json
RTL_LANGS = {"ar", "he", "fa", "ur"}
TR = {
    "en": {
        "m_autostart": "Start with Windows",
        "m_refresh": "Refresh now",
        "m_lock": "Lock position",
        "m_reset": "Reset position",
        "m_monitor": "Monitor for the widget",
        "m_monitor_n": "Monitor {n}",
        "m_primary": "(primary)",
        "m_no_taskbar": "(no taskbar)",
        "m_settings": "Weather settings...",
        "m_version": "Version {v}",
        "m_exit": "Exit",
        "m_language": "Language",
        "m_lang_auto": "Auto (Windows language)",
        "w_loading": "loading the weather...",
        "w_feels": "Feels like {v}{u}",
        "w_wind": "Wind: {v} m/s",
        "w_hum": "Humidity: {v}%",
        "d_title": "Weather settings",
        "d_loc": "Location",
        "d_loc_auto": "Automatic",
        "d_loc_manual": "Manual",
        "d_search_label": "City or coordinates",
        "d_search": "Search",
        "d_not_found": "Nothing found",
        "d_units": "Units",
        "d_interval": "Refresh, min",
        "d_theme": "Theme",
        "d_theme_sys": "Follow Windows",
        "d_theme_dark": "Dark",
        "d_theme_light": "Light",
        "d_save": "Save",
        "d_cancel": "Cancel",
        "c_clear": "Clear", "c_mostly_clear": "Mostly clear", "c_partly": "Partly cloudy",
        "c_overcast": "Overcast", "c_fog": "Fog", "c_drizzle": "Drizzle", "c_rain": "Rain",
        "c_showers": "Showers", "c_snow": "Snow", "c_snow_showers": "Snow showers",
        "c_thunder": "Thunderstorm",
    },
    "uk": {
        "m_autostart": "Запускати разом з Windows",
        "m_refresh": "Оновити зараз",
        "m_lock": "Закріпити положення",
        "m_reset": "Скинути положення",
        "m_monitor": "Монітор для віджета",
        "m_monitor_n": "Монітор {n}",
        "m_primary": "(основний)",
        "m_no_taskbar": "(немає панелі завдань)",
        "m_settings": "Налаштувати погоду...",
        "m_version": "Версія {v}",
        "m_exit": "Вихід",
        "m_language": "Мова",
        "m_lang_auto": "Авто (мова Windows)",
        "w_loading": "завантаження погоди...",
        "w_feels": "Відчувається як {v}{u}",
        "w_wind": "Вітер: {v} м/с",
        "w_hum": "Вологість: {v}%",
        "d_title": "Налаштування погоди",
        "d_loc": "Місцезнаходження",
        "d_loc_auto": "Автоматично",
        "d_loc_manual": "Вручну",
        "d_search_label": "Місто або координати",
        "d_search": "Знайти",
        "d_not_found": "Нічого не знайдено",
        "d_units": "Одиниці",
        "d_interval": "Оновлення, хв",
        "d_theme": "Тема",
        "d_theme_sys": "Як у Windows",
        "d_theme_dark": "Темна",
        "d_theme_light": "Світла",
        "d_save": "Зберегти",
        "d_cancel": "Скасувати",
        "c_clear": "Ясно", "c_mostly_clear": "Переважно ясно", "c_partly": "Мінлива хмарність",
        "c_overcast": "Похмуро", "c_fog": "Туман", "c_drizzle": "Мряка", "c_rain": "Дощ",
        "c_showers": "Злива", "c_snow": "Сніг", "c_snow_showers": "Снігопад", "c_thunder": "Гроза",
    },
}
LANG_NAMES = {"en": "English", "uk": "Українська"}

ext_langs = {}       # мови з файлів lang/*.json
lang_override = ""   # "" = автоматично (мова Windows)
lang_code = "en"

def load_external_langs():
    """lang/xx.json поруч з програмою: додає нові мови або перекриває окремі рядки вбудованих."""
    try:
        for fn in sorted(os.listdir(LANG_DIR)):
            if not fn.lower().endswith(".json") or fn.startswith("_"):
                continue
            try:
                with open(os.path.join(LANG_DIR, fn), encoding="utf-8-sig") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    ext_langs[fn[:-5]] = {k: v for k, v in d.items() if isinstance(v, str)}
            except (OSError, ValueError):
                pass
    except OSError:
        pass

def lang_codes():
    codes = list(TR)
    codes += [c for c in ext_langs if c not in codes]
    return codes

def lang_name(code):
    return ext_langs.get(code, {}).get("_name") or LANG_NAMES.get(code, code)

def ui_languages():
    """Мови інтерфейсу Windows за пріоритетом (напр. ['uk-UA', 'en-US'])."""
    out = []
    try:
        n, size = wt.ULONG(0), wt.ULONG(0)
        k32.GetUserPreferredUILanguages(8, ctypes.byref(n), None, ctypes.byref(size))  # MUI_LANGUAGE_NAME
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value)
            if k32.GetUserPreferredUILanguages(8, ctypes.byref(n), buf, ctypes.byref(size)):
                out = [x for x in buf[:size.value].split("\0") if x]
    except Exception:
        pass
    if not out:
        try:
            b = ctypes.create_unicode_buffer(85)
            if k32.GetUserDefaultLocaleName(b, 85):
                out = [b.value]
        except Exception:
            pass
    return out

def map_lang_tag(tag, codes):
    """'ja-JP' -> 'ja', 'zh-TW' -> 'zh-Hant', 'pt-BR' -> 'pt' (якщо така мова є серед codes)."""
    tl = tag.lower()
    head = tl.split("-")[0]
    if head == "zh":
        cand = ["zh-Hant" if any(x in tl for x in ("tw", "hk", "mo", "hant")) else "zh-Hans"]
    elif head in ("nb", "nn", "no"):
        cand = ["nb", "no"]
    else:
        cand = [tag, head]
    for c in cand:
        for a in codes:
            if a.lower() == c.lower():
                return a
    return None

def detect_lang(codes):
    for tag in ui_languages():
        c = map_lang_tag(tag, codes)
        if c:
            return c
    return "en"

def set_language(override=None):
    global lang_code, lang_override
    if override is not None:
        lang_override = override
    codes = lang_codes()
    lang_code = lang_override if lang_override in codes else detect_lang(codes)

def is_rtl():
    return lang_code.split("-")[0] in RTL_LANGS

def t(key, **kw):
    """Переклад рядка: lang/xx.json > вбудований переклад > англійська > сам ключ."""
    s = None
    for table in (ext_langs.get(lang_code), TR.get(lang_code), TR["en"], ext_langs.get("en")):
        if table and key in table:
            s = table[key]
            break
    if s is None:
        s = key
    try:
        return s.format(**kw) if kw else s
    except (KeyError, IndexError, ValueError):
        return s

# --- налаштування в реєстрі (HKCU\Software\WeatherTray) ---
SETTINGS_KEY = r"Software\WeatherTray"

def reg_get(name, default):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            return int(winreg.QueryValueEx(k, name)[0])
    except (OSError, ValueError):
        return default

def reg_set(name, value):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))
    except OSError:
        pass

def reg_get_str(name, default=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return default

def reg_set_str(name, value):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except OSError:
        pass

# налаштування погоди (кеш у пам'яті; зберігається в реєстрі)
cfg = {"loc_mode": "auto", "m_name": "", "m_lat": "", "m_lon": "", "units": "c",
       "interval": 15, "theme": 0}

def load_cfg():
    cfg["loc_mode"] = reg_get_str("loc_mode", "auto")
    cfg["m_name"] = reg_get_str("m_name", "")
    cfg["m_lat"] = reg_get_str("m_lat", "")
    cfg["m_lon"] = reg_get_str("m_lon", "")
    cfg["units"] = reg_get_str("units", "c")
    cfg["interval"] = min(180, max(5, reg_get("interval", 15)))
    cfg["theme"] = reg_get("theme", 0)  # 0 - як у Windows, 1 - темна, 2 - світла

def save_cfg():
    reg_set_str("loc_mode", cfg["loc_mode"])
    reg_set_str("m_name", cfg["m_name"])
    reg_set_str("m_lat", cfg["m_lat"])
    reg_set_str("m_lon", cfg["m_lon"])
    reg_set_str("units", cfg["units"])
    reg_set("interval", cfg["interval"])
    reg_set("theme", cfg["theme"])

def cfg_theme():
    return cfg["theme"]

# ---------------- автозапуск ----------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def launch_cmd():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{os.path.abspath(__file__)}"'

def autostart_on():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False

def set_autostart(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_cmd())
            else:
                winreg.DeleteValue(k, APP)
    except OSError:
        pass

def first_run_autostart():
    """При першому запуску вмикає автозапуск (далі керується з меню)."""
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY).Close()
    except OSError:
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY).Close()
        set_autostart(True)

# ---------------- погода: геолокація, пошук місць, дані ----------------
lock = threading.Lock()
state = {"cur": None, "loc": None, "ts": 0.0}
wake = threading.Event()
WM_APP_UPDATE = 0x8001
WM_DLG_SEARCH = 0x8002
hwnd_main = None

def http_json(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP}/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def locate_by_ip():
    """Наближена геолокація за IP. Повертає (lat, lon, місто)."""
    attempts = (
        ("https://ipwho.is/", lambda d: (d["success"], d["latitude"], d["longitude"], d.get("city", ""))),
        ("https://ipapi.co/json/", lambda d: (d.get("latitude") is not None, d.get("latitude"),
                                              d.get("longitude"), d.get("city", ""))),
        ("http://ip-api.com/json/?fields=status,city,lat,lon",
         lambda d: (d.get("status") == "success", d.get("lat"), d.get("lon"), d.get("city", ""))),
    )
    for url, parse in attempts:
        try:
            ok, lat, lon, city = parse(http_json(url))
            if ok and lat is not None and lon is not None:
                return float(lat), float(lon), city or ""
        except Exception:
            continue
    raise RuntimeError("geolocation failed")

COORDS_RE = re.compile(r"\s*(-?\d+(?:[.,]\d+)?)(?:\s*;\s*|,\s+|\s+)(-?\d+(?:[.,]\d+)?)\s*")

def geocode(query, lang):
    """Міста, селища, райони міст (OpenStreetMap) або координати. [(підпис, lat, lon, коротка назва)]"""
    m = COORDS_RE.fullmatch(query)
    if m:
        lat = float(m.group(1).replace(",", "."))
        lon = float(m.group(2).replace(",", "."))
        if abs(lat) <= 90 and abs(lon) <= 180:
            lbl = f"{lat:.4f}, {lon:.4f}"
            return [(lbl, lat, lon, lbl)]
    out = []
    try:
        q = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 12, "dedupe": 1,
                                    "addressdetails": 1, "accept-language": lang})
        data = http_json("https://nominatim.openstreetmap.org/search?" + q)
        places = [r for r in data if r.get("category") in ("place", "boundary")] or data
        for r in places:
            a = r.get("address", {})
            name = r.get("name") or r.get("display_name", "").split(",")[0]
            parent = (a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
                      or a.get("county") or a.get("state") or "")
            if r.get("addresstype") in ("city", "town", "village", "hamlet", "municipality") \
                    or not parent or parent == name:
                short = name
            else:
                short = f"{name}, {parent}"
            label = ", ".join(r.get("display_name", short).split(", ")[:4])
            out.append((label[:95], float(r["lat"]), float(r["lon"]), short))
    except Exception:
        out = []
    if out:
        return out
    q = urllib.parse.urlencode({"name": query, "count": 10, "language": lang})
    data = http_json("https://geocoding-api.open-meteo.com/v1/search?" + q)
    for r in data.get("results", []) or []:
        label = ", ".join(x for x in (r.get("name"), r.get("admin2"), r.get("admin1"),
                                      r.get("country")) if x)
        out.append((label[:95], r["latitude"], r["longitude"], r.get("name", label)))
    return out

def fetch_weather(lat, lon, fahrenheit):
    p = {"latitude": lat, "longitude": lon, "timezone": "auto", "wind_speed_unit": "ms",
         "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "weather_code,wind_speed_10m,is_day"}
    if fahrenheit:
        p["temperature_unit"] = "fahrenheit"
    return http_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(p))["current"]

# код WMO -> (ключ опису, тип іконки)
WMO = {0: ("clear", "clear"), 1: ("mostly_clear", "partly"), 2: ("partly", "partly"),
       3: ("overcast", "cloud"), 45: ("fog", "fog"), 48: ("fog", "fog"),
       51: ("drizzle", "rain"), 53: ("drizzle", "rain"), 55: ("drizzle", "rain"),
       56: ("drizzle", "rain"), 57: ("drizzle", "rain"),
       61: ("rain", "rain"), 63: ("rain", "rain"), 65: ("rain", "rain"),
       66: ("rain", "rain"), 67: ("rain", "rain"),
       71: ("snow", "snow"), 73: ("snow", "snow"), 75: ("snow", "snow"), 77: ("snow", "snow"),
       80: ("showers", "rain"), 81: ("showers", "rain"), 82: ("showers", "rain"),
       85: ("snow_showers", "snow"), 86: ("snow_showers", "snow"),
       95: ("thunder", "thunder"), 96: ("thunder", "thunder"), 99: ("thunder", "thunder")}

def weather_loop():
    """Фоновий потік: визначає місце (геолокація або вручну) і оновлює погоду."""
    while True:
        ok = False
        try:
            with lock:
                prev_loc = state["loc"]
            if cfg["loc_mode"] == "manual" and cfg["m_lat"] != "":
                loc = (float(cfg["m_lat"]), float(cfg["m_lon"]), cfg["m_name"])
            else:
                try:
                    loc = locate_by_ip()
                except Exception:
                    if not prev_loc:
                        raise
                    loc = prev_loc
            cur = fetch_weather(loc[0], loc[1], cfg["units"] == "f")
            with lock:
                state["cur"], state["loc"], state["ts"] = cur, loc, time.time()
            ok = True
            if hwnd_main:
                user32.PostMessageW(hwnd_main, WM_APP_UPDATE, 0, 0)
        except Exception:
            pass
        wake.wait(cfg["interval"] * 60 if ok else 30)
        wake.clear()

def weather_view():
    """(текст на віджеті, тип іконки, вдень?, текст підказки)"""
    with lock:
        cur, loc = state["cur"], state["loc"]
    if not cur:
        return "--°", "cloud", True, t("w_loading")
    unit = "°F" if cfg["units"] == "f" else "°C"
    group, kind = WMO.get(cur["weather_code"], ("overcast", "cloud"))
    lines = [f"{round(cur['temperature_2m'])}{unit}, {t('c_' + group)}"]
    if loc and loc[2]:
        lines.append(loc[2])
    lines += [t("w_feels", v=round(cur["apparent_temperature"]), u=unit),
              t("w_wind", v=round(cur["wind_speed_10m"])),
              t("w_hum", v=cur["relative_humidity_2m"])]
    return f"{round(cur['temperature_2m'])}°", kind, bool(cur.get("is_day", 1)), "\n".join(lines)

# ---------------- віджети біля трея: [DPI 1600] [мишка 93%] ----------------
SS = 3  # супервибірка для згладжування
HINST = None
dpi_widget_enabled = True
offset_dp = 8  # відступ від трея вліво (при 100% масштабі), можна перетягнути мишею
GAP_DP = 4     # проміжок між віджетами
monitor_dev = ""    # обраний монітор (ім'я пристрою, напр. DISPLAY2); "" = основний
active_dev = ""     # монітор, на якому віджети зараз реально показані
locked = False      # True - положення закріплено, перетягування заборонене
menu_monitors = []  # список моніторів, показаний у меню
menu_langs = []     # список мов, показаний у меню
_scale = {"v": None}
drag = {"active": False, "x0": 0, "off0": 0, "moved": False}
widgets = {}   # hwnd -> Widget
TIP_DARK_BG = (43, 43, 43)
TIP_DARK_FG = (255, 255, 255)
TIP_LIGHT_BG = (249, 249, 249)
TIP_LIGHT_FG = (26, 26, 26)
TIP_LIGHT_BORDER = (205, 205, 205)  # тонка рамка лише у світлій темі
FONT_FACES = ("Segoe UI Variable Text", "Segoe UI")  # шрифт Windows 11 (як у меню Пуск)

def get_scale():
    if _scale["v"]:
        return _scale["v"]
    try:
        return max(1.0, user32.GetDpiForSystem() / 96.0)
    except (AttributeError, OSError):
        return 1.0

def dpi_scale_of(hwnd):
    try:
        d = user32.GetDpiForWindow(hwnd)
        if d:
            return max(1.0, d / 96.0)
    except (AttributeError, OSError):
        pass
    return None

def light_theme():
    th = cfg_theme()
    if th == 1:
        return False
    if th == 2:
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False

def theme_color():
    return (20, 20, 20) if light_theme() else (240, 240, 240)

def monitor_list():
    """[(hmonitor, ім'я_пристрою, основний?)], основний - першим."""
    mons = []
    def cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            mons.append((hmon, mi.szDevice, bool(mi.dwFlags & 1)))
        return True
    proc = MONITORENUMPROC(cb)
    user32.EnumDisplayMonitors(None, None, proc, 0)
    mons.sort(key=lambda m: (not m[2], m[1]))
    return mons

def monitor_label(dev, primary):
    m = re.search(r"(\d+)$", dev or "")
    name = t("m_monitor_n", n=m.group(1) if m else "?")
    return name + (" " + t("m_primary") if primary else "")

def offset_key(dev):
    return "offset_" + re.sub(r"[^0-9A-Za-z]", "", dev or "")

def find_taskbar_for(hmon):
    """Панель завдань, що стоїть на заданому моніторі (основна або додаткова)."""
    cands = []
    tb = user32.FindWindowW("Shell_TrayWnd", None)
    if tb:
        cands.append(tb)
    prev = None
    while True:
        h = user32.FindWindowExW(None, prev, "Shell_SecondaryTrayWnd", None)
        if not h:
            break
        cands.append(h)
        prev = h
    for h in cands:
        if user32.MonitorFromWindow(h, 2) == hmon:  # MONITOR_DEFAULTTONEAREST
            return h
    return None

def taskbar_info():
    """(вікно панелі, її прямокутник, прямокутник трея) для обраного монітора."""
    global active_dev, offset_dp
    mons = monitor_list()
    if not mons:
        return None
    m = None
    if monitor_dev:
        for c in mons:
            if c[1] == monitor_dev and find_taskbar_for(c[0]):
                m = c
                break
    if m is None:  # обраного монітора немає або на ньому немає панелі - основний
        m = next((c for c in mons if c[2]), mons[0])
    tb = find_taskbar_for(m[0])
    if not tb:
        return None
    if m[1] != active_dev:  # перемкнули монітор - підхоплюємо його збережений відступ
        active_dev = m[1]
        offset_dp = reg_get(offset_key(active_dev), reg_get("offset", 8))
    _scale["v"] = dpi_scale_of(tb)
    rtb = wt.RECT()
    if not user32.GetWindowRect(tb, ctypes.byref(rtb)):
        return None
    if (rtb.bottom - rtb.top) > (rtb.right - rtb.left):  # вертикальна панель - не підтримується
        return None
    rtray = wt.RECT()
    tray = user32.FindWindowExW(tb, None, "TrayNotifyWnd", None)
    if not (tray and user32.GetWindowRect(tray, ctypes.byref(rtray))):
        # на додатковій панелі трея немає - лише годинник: відступаємо від правого краю
        rtray.left = rtb.right - int((120 if m[2] is False else 260) * get_scale())
    return tb, rtb, rtray

# ---------------- меню у стилі Windows 11 (тема Windows + іконки Segoe Fluent) ----------------
ICON_FACES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
MENU_ICONS = {"autostart": 0xE768, "refresh": 0xE72C, "lock": 0xE72E, "reset": 0xE777,
              "monitor": 0xE7F4, "settings": 0xE713, "exit": 0xE7E8, "language": 0xE774}

def apply_menu_theme():
    """Змушує popup-меню слідувати темі Windows (темна/світла). Недокументовані
    функції uxtheme: SetPreferredAppMode (ординал 135) і FlushMenuThemes (136)."""
    try:
        set_mode = uxtheme[135]
        set_mode.restype = ctypes.c_int
        set_mode.argtypes = [ctypes.c_int]
        flush = uxtheme[136]
        flush.restype = None
        flush.argtypes = []
        set_mode(3 if light_theme() else 2)  # 3 = ForceLight, 2 = ForceDark
        flush()
    except Exception:
        pass

def make_menu_icon(codepoint):
    """Іконка-гліф Segoe Fluent Icons -> 32-бітний ARGB bitmap кольору тексту теми (для hbmpItem)."""
    sc = get_scale()
    px = max(16, int(round(16 * sc)))
    S = 4
    W = px * S
    hdc0 = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc0)
    font, oldf = pick_font(mdc, W, ICON_FACES)
    ch = chr(codepoint)
    sz = wt.SIZE()
    gdi32.GetTextExtentPoint32W(mdc, ch, 1, ctypes.byref(sz))
    bmi = BITMAPINFOHEADER(40, W, -W, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    oldb = gdi32.SelectObject(mdc, dib)
    gdi32.SetBkMode(mdc, 1)
    gdi32.SetTextColor(mdc, 0xFFFFFF)
    gdi32.TextOutW(mdc, (W - sz.cx) // 2, (W - sz.cy) // 2, ch, 1)
    gdi32.GdiFlush()
    arr = (ctypes.c_uint32 * (W * W)).from_address(bits.value)
    r, g, b = theme_color()
    n = S * S
    out = [0] * (px * px)
    for y in range(px):
        acc = [0] * px
        for dy in range(S):
            base = (y * S + dy) * W
            row = arr[base:base + W]
            for dx in range(S):
                acc = [a + (v & 0xFF) for a, v in zip(acc, row[dx::S])]
        for x in range(px):
            cov = acc[x] // n
            if cov:
                out[y * px + x] = (cov << 24) | ((r * cov // 255) << 16) | ((g * cov // 255) << 8) | (b * cov // 255)
    gdi32.SelectObject(mdc, oldb)
    gdi32.DeleteObject(dib)
    gdi32.SelectObject(mdc, oldf)
    gdi32.DeleteObject(font)
    gdi32.DeleteDC(mdc)
    # фінальний bitmap потрібного розміру
    fbmi = BITMAPINFOHEADER(40, px, -px, 1, 32, 0, 0, 0, 0, 0, 0)
    fbits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(hdc0, ctypes.byref(fbmi), 0, ctypes.byref(fbits), None, 0)
    farr = (ctypes.c_uint32 * (px * px)).from_address(fbits.value)
    farr[:] = out
    user32.ReleaseDC(None, hdc0)
    return hbm

def menu_add(menu, text="", cid=0, checked=False, grayed=False, hbm=None, sub=None, sep=False):
    mii = MENUITEMINFOW()
    mii.cbSize = ctypes.sizeof(MENUITEMINFOW)
    if sep:
        mii.fMask = 0x100   # MIIM_FTYPE
        mii.fType = 0x800   # MFT_SEPARATOR
    else:
        mii.fMask = 0x1 | 0x40 | (0x2 if cid else 0) | (0x80 if hbm else 0) | (0x4 if sub else 0)
        mii.fState = (0x3 if grayed else 0) | (0x8 if checked else 0)
        mii.wID = cid
        mii.dwTypeData = text
        mii.hbmpItem = hbm
        mii.hSubMenu = sub
    user32.InsertMenuItemW(menu, user32.GetMenuItemCount(menu), True, ctypes.byref(mii))

def tick(active):
    """Галочка в кінці рядка: текст після табуляції меню вирівнює праворуч."""
    return "\t\u2713" if active else ""

def pick_font(mdc, px, faces=FONT_FACES):
    """Шрифт Windows 11 (Segoe UI Variable Text); якщо його немає - Segoe UI."""
    face_buf = ctypes.create_unicode_buffer(64)
    font = None
    for face in faces:
        f = gdi32.CreateFontW(-px, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, face)
        old = gdi32.SelectObject(mdc, f)
        gdi32.GetTextFaceW(mdc, 64, face_buf)
        if face_buf.value.lower() == face.lower() or face == faces[-1]:
            return f, old
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(f)
    return font, None

class _Grid:
    """Малювання білим на чорному в сітці 24x24 (супервибірка вже врахована в розмірі isz)."""
    def __init__(self, mdc, ix, iy, isz):
        self.m, self.x, self.y, self.u = mdc, ix, iy, isz / 24.0

    def X(self, v):
        return int(round(self.x + v * self.u))

    def Y(self, v):
        return int(round(self.y + v * self.u))

    def white(self):
        gdi32.SelectObject(self.m, gdi32.GetStockObject(0))  # WHITE_BRUSH
        gdi32.SelectObject(self.m, gdi32.GetStockObject(6))  # WHITE_PEN

    def black(self):
        gdi32.SelectObject(self.m, gdi32.GetStockObject(4))  # BLACK_BRUSH
        gdi32.SelectObject(self.m, gdi32.GetStockObject(7))  # BLACK_PEN

    def ell(self, x1, y1, x2, y2):
        gdi32.Ellipse(self.m, self.X(x1), self.Y(y1), self.X(x2), self.Y(y2))

    def rrect(self, x1, y1, x2, y2, r):
        d = int(2 * r * self.u)
        gdi32.RoundRect(self.m, self.X(x1), self.Y(y1), self.X(x2), self.Y(y2), d, d)

    def poly(self, pts):
        arr = (wt.POINT * len(pts))(*[wt.POINT(self.X(a), self.Y(b)) for a, b in pts])
        gdi32.Polygon(self.m, arr, len(pts))

    def line(self, x1, y1, x2, y2, w=1.8):
        pen = gdi32.CreatePen(0, max(1, int(w * self.u)), 0xFFFFFF)
        op = gdi32.SelectObject(self.m, pen)
        gdi32.MoveToEx(self.m, self.X(x1), self.Y(y1), None)
        gdi32.LineTo(self.m, self.X(x2), self.Y(y2))
        gdi32.SelectObject(self.m, op)
        gdi32.DeleteObject(pen)


def _cloud(g, dx, dy):
    g.white()
    g.ell(2 + dx, 10 + dy, 11 + dx, 19 + dy)
    g.ell(7 + dx, 5.5 + dy, 18 + dx, 16.5 + dy)
    g.ell(13 + dx, 10 + dy, 22 + dx, 19 + dy)
    g.rrect(5 + dx, 13 + dy, 19 + dx, 19 + dy, 3)

def _sun(g, cx, cy, r):
    g.white()
    g.ell(cx - r, cy - r, cx + r, cy + r)
    for i in range(8):
        a = math.radians(i * 45)
        g.line(cx + math.cos(a) * (r + 2), cy + math.sin(a) * (r + 2),
               cx + math.cos(a) * (r + 4.2), cy + math.sin(a) * (r + 4.2))

def _moon(g, cx, cy, r):
    g.white()
    g.ell(cx - r, cy - r, cx + r, cy + r)
    g.black()
    ox, oy, rr = cx + r * 0.65, cy - r * 0.35, r * 0.9
    g.ell(ox - rr, oy - rr, ox + rr, oy + rr)

def icon_layers(kind, is_day, light):
    """[(функція малювання, колір)] знизу вгору."""
    cloud_c = (125, 138, 152) if light else (223, 229, 236)
    sun_c = (255, 200, 61)
    moon_c = (208, 185, 78) if light else (241, 233, 192)
    rain_c = (74, 163, 255)
    snow_c = (90, 169, 230) if light else (154, 212, 255)
    if kind == "clear":
        return [((lambda g: _sun(g, 12, 12, 5)) if is_day else (lambda g: _moon(g, 12, 12, 7)),
                 sun_c if is_day else moon_c)]
    if kind == "partly":
        return [((lambda g: _sun(g, 8, 8, 3.6)) if is_day else (lambda g: _moon(g, 8, 8, 4.6)),
                 sun_c if is_day else moon_c),
                (lambda g: _cloud(g, 2, 3), cloud_c)]
    if kind == "fog":
        def fog(g):
            _cloud(g, 0, -4)
            for i, (a, b) in enumerate(((4, 20), (6, 18), (4, 20))):
                g.line(a, 17 + i * 3, b, 17 + i * 3, 1.6)
        return [(fog, cloud_c)]
    if kind == "rain":
        def drops(g):
            g.white()
            for x in (8, 12.5, 17):
                g.line(x, 17, x - 1.5, 21.5)
        return [(lambda g: _cloud(g, 0, -4), cloud_c), (drops, rain_c)]
    if kind == "snow":
        def flakes(g):
            g.white()
            for x, y in ((8, 19), (12.5, 21.5), (17, 19)):
                g.ell(x - 1.5, y - 1.5, x + 1.5, y + 1.5)
        return [(lambda g: _cloud(g, 0, -4), cloud_c), (flakes, snow_c)]
    if kind == "thunder":
        def bolt(g):
            g.white()
            g.poly([(13.5, 13), (8.5, 20), (12, 20), (10.5, 24), (16.5, 16.5), (13, 16.5)])
        return [(lambda g: _cloud(g, 0, -4), cloud_c), (bolt, sun_c)]
    return [(lambda g: _cloud(g, 0, 0), cloud_c)]  # cloud


def draw_widget_bitmap(text, color, kind, is_day, h):
    """Іконка погоди + температура: у S-кратному розмірі, потім зменшення -> згладжена піксельна прозорість."""
    sc = get_scale()
    S = SS
    hdc0 = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc0)
    fh = max(8, int(round(15 * sc))) * S
    font, oldf = pick_font(mdc, fh)
    sz = wt.SIZE()
    gdi32.GetTextExtentPoint32W(mdc, text, len(text), ctypes.byref(sz))
    tw = sz.cx
    pad = int(4 * sc * S)
    isz = int(20 * sc * S)
    gap = int(4 * sc * S)
    W = pad + isz + gap + tw + pad
    w = (W + S - 1) // S
    W, H = w * S, h * S
    tm = TEXTMETRICW()
    gdi32.GetTextMetricsW(mdc, ctypes.byref(tm))
    cap = 0.70 * (tm.tmHeight - tm.tmInternalLeading)  # висота цифр
    ty = int(H / 2 + cap / 2 - tm.tmAscent)            # їхній центр = центр панелі
    ix, iy = pad, (H - isz) // 2
    tx = pad + isz + gap

    def mask(draw):
        bmi = BITMAPINFOHEADER(40, W, -H, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        dib = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(mdc, dib)
        draw()
        gdi32.GdiFlush()
        cov = _ss_cov((ctypes.c_uint32 * (W * H)).from_address(bits.value), W, S, w, h)
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(dib)
        return cov

    def draw_text():
        gdi32.SetBkMode(mdc, 1)
        gdi32.SetTextColor(mdc, 0xFFFFFF)
        gdi32.TextOutW(mdc, tx, ty, text, len(text))

    layers = []
    for fn, col in icon_layers(kind, is_day, light_theme()):
        layers.append((mask(lambda f=fn: f(_Grid(mdc, ix, iy, isz))), col))
    layers.append((mask(draw_text), color))

    gdi32.SelectObject(mdc, oldf)
    gdi32.DeleteObject(font)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(None, hdc0)

    out = [0] * (w * h)
    for i in range(w * h):
        pr = pg = pb = pa = 0  # попередньо помножений ARGB
        for cov, (r, g, b) in layers:
            c = cov[i]
            if not c:
                continue
            inv = 255 - c
            pr = r * c // 255 + pr * inv // 255
            pg = g * c // 255 + pg * inv // 255
            pb = b * c // 255 + pb * inv // 255
            pa = c + pa * inv // 255
        out[i] = 0x01000000 if not pa else (pa << 24) | (pr << 16) | (pg << 8) | pb  # майже невидимий - ловить клік
    return w, out

def apply_bitmap(hwnd, w, h, out):
    hdc0 = user32.GetDC(None)
    bmi = BITMAPINFOHEADER(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(hdc0, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    fdc = gdi32.CreateCompatibleDC(hdc0)
    old = gdi32.SelectObject(fdc, dib)
    arr = (ctypes.c_uint32 * (w * h)).from_address(bits.value)
    arr[:] = out
    size = wt.SIZE(w, h)
    src = wt.POINT(0, 0)
    bf = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, AC_SRC_ALPHA
    user32.UpdateLayeredWindow(hwnd, hdc0, None, ctypes.byref(size), fdc,
                               ctypes.byref(src), 0, ctypes.byref(bf), 2)
    gdi32.SelectObject(fdc, old)
    gdi32.DeleteObject(dib)
    gdi32.DeleteDC(fdc)
    user32.ReleaseDC(None, hdc0)

class Widget:
    """Прозоре дочірнє вікно панелі завдань: іконка погоди + температура."""
    def __init__(self):
        self.hwnd = None
        self.parent = None
        self.key = None
        self.pending = None
        self.size = [1, 1]
        self.tip_text = ""

    def alive(self):
        return bool(self.hwnd) and bool(user32.IsWindow(self.hwnd))

    def create(self, tb):
        # WS_EX_LAYERED | WS_EX_NOACTIVATE ; WS_CHILD | WS_VISIBLE
        hw = user32.CreateWindowExW(0x80000 | 0x08000000, "WeatherTrayWidget", "", 0x40000000 | 0x10000000,
                                    0, 0, 10, 10, tb, None, HINST, None)
        if not hw:
            return False
        self.hwnd, self.parent, self.key, self.pending = hw, tb, None, None
        widgets[hw] = self
        return True

    def destroy(self):
        hide_tip(self)
        if self.hwnd:
            widgets.pop(self.hwnd, None)
            if user32.IsWindow(self.hwnd):
                user32.DestroyWindow(self.hwnd)
        self.hwnd, self.key, self.pending = None, None, None

    def render(self, h):
        text, kind, is_day, _ = weather_view()
        color = theme_color()
        key = (text, kind, is_day, color, h, get_scale())
        if key != self.key:
            w, out = draw_widget_bitmap(text, color, kind, is_day, h)
            self.size = [w, h]
            self.pending = out
            self.key = key

    def set_tip(self, text):
        self.tip_text = text
        if tip_state["owner"] is self and tip_state["text"] != text:  # текст змінився, поки підказка видима
            show_tip(self)

# ---------------- власна підказка (без системної рамки), підлаштовується під тему ----------------
tip_state = {"hwnd": None, "owner": None, "text": None}

def _ss_cov(arr, W, S, w, h):
    """Зменшує маску в S разів -> покриття 0..255 для кожного пікселя (список w*h)."""
    n = S * S
    out = [0] * (w * h)
    for y in range(h):
        acc = [0] * w
        for dy in range(S):
            base = (y * S + dy) * W
            row = arr[base:base + W]
            for dx in range(S):
                acc = [a + (v & 0xFF) for a, v in zip(acc, row[dx::S])]
        o = y * w
        for x in range(w):
            out[o + x] = acc[x] // n
    return out

def draw_tip_bitmap(text):
    """Заокруглений прямокутник + текст (шрифт Windows 11), піксельна прозорість. Темна тема - без рамки."""
    sc = get_scale()
    S = 3
    dark = not light_theme()
    bg, fg = (TIP_DARK_BG, TIP_DARK_FG) if dark else (TIP_LIGHT_BG, TIP_LIGHT_FG)
    lines = text.split("\n")
    hdc0 = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc0)
    font, oldf = pick_font(mdc, max(9, int(round(12 * sc))) * S)
    tm = TEXTMETRICW()
    gdi32.GetTextMetricsW(mdc, ctypes.byref(tm))
    line_h = tm.tmHeight + int(3 * sc * S)
    widths = []
    for ln in lines:
        sz = wt.SIZE()
        gdi32.GetTextExtentPoint32W(mdc, ln, len(ln), ctypes.byref(sz))
        widths.append(sz.cx)
    padx, pady = int(10 * sc * S), int(7 * sc * S)
    w = (max(widths) + 2 * padx + S - 1) // S
    h = (len(lines) * line_h + 2 * pady + S - 1) // S
    W, H = w * S, h * S
    white = 0xFFFFFF

    def mask(draw):
        bmi = BITMAPINFOHEADER(40, W, -H, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        dib = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(mdc, dib)
        draw()
        gdi32.GdiFlush()
        cov = _ss_cov((ctypes.c_uint32 * (W * H)).from_address(bits.value), W, S, w, h)
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(dib)
        return cov

    def rounded(inset):
        def draw():
            br = gdi32.CreateSolidBrush(white)
            ob = gdi32.SelectObject(mdc, br)
            op = gdi32.SelectObject(mdc, gdi32.GetStockObject(6))  # WHITE_PEN
            r = max(2, int(6 * sc * S) - inset)
            gdi32.RoundRect(mdc, inset, inset, W - inset, H - inset, 2 * r, 2 * r)
            gdi32.SelectObject(mdc, op)
            gdi32.SelectObject(mdc, ob)
            gdi32.DeleteObject(br)
        return draw

    def draw_text():
        gdi32.SetBkMode(mdc, 1)
        gdi32.SetTextColor(mdc, white)
        for i, ln in enumerate(lines):
            gdi32.TextOutW(mdc, padx, pady + i * line_h, ln, len(ln))

    shape = mask(rounded(0))
    inner = shape if dark else mask(rounded(S))  # внутрішня частина: решта - тонка рамка (лише світла тема)
    txt = mask(draw_text)
    gdi32.SelectObject(mdc, oldf)
    gdi32.DeleteObject(font)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(None, hdc0)

    out = [0] * (w * h)
    for i in range(w * h):
        a = shape[i]
        if not a:
            continue
        ic = 255 if dark else min(255, inner[i] * 255 // a)  # частка "всередині" для цього пікселя
        tc = txt[i]
        px = 0
        for ch in range(3):
            base = (bg[ch] * ic + TIP_LIGHT_BORDER[ch] * (255 - ic)) // 255 if not dark else bg[ch]
            c = (base * (255 - tc) + fg[ch] * tc) // 255
            px = (px << 8) | (c * a // 255)
        out[i] = (a << 24) | px
    return w, h, out

def show_tip(widget):
    try:
        text = widget.tip_text
        if not text or not widget.hwnd:
            return
        th = tip_state["hwnd"]
        if th and tip_state["owner"] is widget and tip_state["text"] == text and user32.IsWindowVisible(th):
            return
        if not th or not user32.IsWindow(th):
            # LAYERED | TOOLWINDOW | TOPMOST | NOACTIVATE | TRANSPARENT (миша проходить крізь підказку); WS_POPUP
            th = user32.CreateWindowExW(0x80000 | 0x80 | 0x8 | 0x08000000 | 0x20, "WeatherTrayTip", "",
                                        0x80000000, 0, 0, 10, 10, None, None, HINST, None)
            if not th:
                return
            tip_state["hwnd"] = th
        tw, tht, out = draw_tip_bitmap(text)
        rc = wt.RECT()
        user32.GetWindowRect(widget.hwnd, ctypes.byref(rc))
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(user32.MonitorFromWindow(widget.hwnd, 2), ctypes.byref(mi))
        gap = int(8 * get_scale())
        x = (rc.left + rc.right) // 2 - tw // 2
        x = max(mi.rcMonitor.left + 4, min(x, mi.rcMonitor.right - tw - 4))
        y = rc.top - tht - gap                      # над віджетом
        if y < mi.rcMonitor.top:                    # панель угорі - під віджетом
            y = rc.bottom + gap
        user32.SetWindowPos(th, ctypes.c_void_p(-1), x, y, tw, tht, 0x10)  # HWND_TOPMOST, NOACTIVATE
        apply_bitmap(th, tw, tht, out)
        user32.ShowWindow(th, 4)  # SW_SHOWNOACTIVATE
        tip_state["owner"], tip_state["text"] = widget, text
    except Exception:
        log_exc()

def hide_tip(widget=None):
    if widget is not None and tip_state["owner"] is not widget:
        return
    th = tip_state["hwnd"]
    if th and user32.IsWindow(th):
        user32.ShowWindow(th, 0)
    tip_state["owner"] = tip_state["text"] = None

def tip_proc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

_tip_proc_ref = WNDPROC(tip_proc)

wx = Widget()

# ---------------- сусідні віджети (інші наші програми на цій же панелі) ----------------
PEER_GAP_DP = 4                                   # проміжок між віджетами різних програм (dp), як усередині X11 Battery
MY_CLASS = "WeatherTrayWidget"
PEER_CLASSES = ("LoadTrayWidget", "X11BatteryWidget",)
applied = {"px": None}                            # останній прийнятий відступ від трея (px)
peer_state = {"yield": False}                     # після скидання позиції поступаємося сусіду при рівних відступах

def peer_spans(tb, rtb):
    """Прямокутники віджетів інших програм на цій панелі: (ліво, право, клас) в координатах панелі."""
    out = []
    try:
        for cls in PEER_CLASSES:
            prev = None
            for _ in range(8):
                h = user32.FindWindowExW(tb, prev, cls, None)
                if not h:
                    break
                prev = h
                if not user32.IsWindowVisible(h):
                    continue
                rc = wt.RECT()
                if user32.GetWindowRect(h, ctypes.byref(rc)) and (rc.right - rc.left) > 12:
                    out.append((rc.left - rtb.left, rc.right - rtb.left, cls))
    except Exception:
        log_exc()
    return out

def nearest_free(off_px, max_px, zones):
    """Найближчий до off_px допустимий відступ поза забороненими зонами (None, якщо місця немає)."""
    def free(o):
        return 0 <= o <= max_px and not any(z[0] + 2 < o < z[1] - 2 for z in zones)
    cands = [off_px] + [z[0] for z in zones] + [z[1] for z in zones] + [0, max_px]
    cands = [c for c in cands if free(c)]
    return min(cands, key=lambda c: abs(c - off_px)) if cands else None

def avoid_peers(off_px, cur_px, max_px, width, tray_x, gap, peers, dragging, yield_all=False):
    """Повертає відступ від трея (px), при якому блок шириною width не торкається сусідніх віджетів
    і між ними лишається проміжок gap. Під час перетягування віджет можна поставити перед сусідом
    або за ним (коли перетягнули за середину сусіда - він перестрибує на інший бік), але ніколи не
    поверх нього. Поза перетягуванням той, хто стоїть далі від трея, відсувається ліворуч."""
    forb = []  # (lo, hi, відступ сусіда від трея, клас): заборонена зона для off
    for a, b, cls in peers:
        forb.append((tray_x - b - gap - width, tray_x - a + gap, tray_x - b, cls))
    if dragging:
        r = nearest_free(off_px, max_px, forb)
        return cur_px if (r is None and cur_px is not None) else (off_px if r is None else r)
    if yield_all:
        mine = forb
    else:
        mine = [f for f in forb if f[2] < off_px or (f[2] == off_px and f[3] < MY_CLASS)]
    for _ in range(len(mine) + 1):
        hit = [f for f in mine if f[0] + 2 < off_px < f[1] - 2]
        if not hit:
            break
        off_px = max(f[1] for f in hit)
    if off_px > max_px or any(f[0] + 2 < off_px < f[1] - 2 for f in mine):
        r = nearest_free(min(off_px, max_px), max_px, mine)  # зліва немає місця - шукаємо з іншого боку
        if r is not None:
            off_px = r
    return off_px

def peer_tick(w):
    """Раз на секунду перевіряємо, чи не накрив нас інший віджет (наприклад, після перемикання монітора)."""
    try:
        if w.alive() and not drag["active"]:
            layout()
    except Exception:
        log_exc()

def place(w, x, h):
    user32.SetWindowPos(w.hwnd, None, x, 0, w.size[0], h, 0x10 | 0x40)  # NOACTIVATE | SHOWWINDOW

def clamp_offset(info):
    """Не даємо віджету заїхати за край панелі (ліворуч), за трей (праворуч) або на віджети інших програм."""
    global offset_dp
    tb, rtb, rtray = info
    sc = get_scale()
    width = wx.size[0]
    max_px = max(0, (rtray.left - rtb.left) - width)
    want = min(max(0, int(offset_dp * sc)), max_px)
    dragging = bool(drag["active"] and drag["moved"])
    off_px = avoid_peers(want, applied["px"], max_px, width, rtray.left - rtb.left, int(PEER_GAP_DP * sc),
                         peer_spans(tb, rtb), dragging, peer_state["yield"])
    off_px = min(max(0, off_px), max_px)
    offset_dp = int(math.ceil(off_px / sc))
    applied["px"] = off_px
    if off_px != want and not dragging:  # зсунулись, щоб не накладатись - запам'ятовуємо нове місце
        reg_set(offset_key(active_dev), offset_dp)

def layout(info=None):
    """Віджет стоїть ліворуч від трея на відстані offset_dp."""
    info = info or taskbar_info()
    if not info:
        return
    tb, rtb, rtray = info
    sc = get_scale()
    h = rtb.bottom - rtb.top
    clamp_offset(info)
    x = rtray.left - rtb.left - wx.size[0] - int(offset_dp * sc)
    if wx.hwnd:
        place(wx, x, h)

def widgets_update(force=False):
    try:
        info = taskbar_info()
        if not info:
            return
        tb, rtb, rtray = info
        h = rtb.bottom - rtb.top
        if not wx.alive() or wx.parent != tb:
            peer_state["yield"] = True
            wx.destroy()
            if not wx.create(tb):
                return
        if force:
            wx.key = None
        wx.render(h)
        layout(info)
        peer_state["yield"] = False
        if wx.hwnd and wx.pending is not None:
            apply_bitmap(wx.hwnd, wx.size[0], wx.size[1], wx.pending)
            wx.pending = None
        if wx.hwnd:
            wx.set_tip(weather_view()[3])
    except Exception:
        log_exc()

def refresh(hwnd=None, add=False):
    widgets_update()

def recreate_widgets():
    wx.destroy()
    widgets_update(force=True)

def toggle_lock():
    global locked
    locked = not locked
    reg_set("locked", int(locked))

def reset_position():
    global offset_dp
    offset_dp = 8
    reg_set(offset_key(active_dev), offset_dp)
    peer_state["yield"] = True   # якщо там уже стоїть сусід - відсуваємось від нього
    try:
        layout()
    finally:
        peer_state["yield"] = False

def select_language(i):
    """i = 0 - автоматично (мова Windows), далі - мови зі списку меню."""
    if i == 0:
        set_language("")
    elif 1 <= i <= len(menu_langs):
        set_language(menu_langs[i - 1])
    else:
        return
    reg_set_str("language", lang_override)
    widgets_update(force=True)

def select_monitor(i):
    global monitor_dev
    if 0 <= i < len(menu_monitors):
        monitor_dev = menu_monitors[i][1]
        reg_set_str("monitor", monitor_dev)
        recreate_widgets()

# ---------------- іконка програми ----------------
dlg_icons = []

def icon_path():
    """WeatherTray.ico: усередині exe (PyInstaller) або поруч зі скриптом."""
    for base in (getattr(sys, "_MEIPASS", None), app_dir()):
        if base:
            p = os.path.join(base, "WeatherTray.ico")
            if os.path.exists(p):
                return p
    return None

def load_icon(size):
    p = icon_path()
    if not p:
        return None
    try:
        return user32.LoadImageW(None, p, 1, size, size, 0x10) or None  # IMAGE_ICON, LR_LOADFROMFILE
    except Exception:
        log_exc()
        return None

def show_menu(hwnd):
    global menu_monitors
    _, _, _, tip = weather_view()
    head = tip.split("\n")
    apply_menu_theme()
    icons = []
    def ic(name):
        try:
            h = make_menu_icon(MENU_ICONS[name])
            icons.append(h)
            return h
        except Exception:
            log_exc()
            return None
    menu = user32.CreatePopupMenu()
    for ln in head[:2]:
        menu_add(menu, ln, grayed=True)
    menu_add(menu, sep=True)
    menu_add(menu, t("m_refresh"), 3, hbm=ic("refresh"))
    menu_add(menu, t("m_autostart") + tick(autostart_on()), 1, hbm=ic("autostart"))
    menu_add(menu, t("m_lock") + tick(locked), 5, hbm=ic("lock"))
    menu_add(menu, t("m_reset"), 7, hbm=ic("reset"))
    menu_monitors = monitor_list()
    if len(menu_monitors) > 1:
        sub = user32.CreatePopupMenu()
        for i, (hmon, dev, prim) in enumerate(menu_monitors):
            has_tb = bool(find_taskbar_for(hmon))
            label = monitor_label(dev, prim) + ("" if has_tb else " " + t("m_no_taskbar"))
            menu_add(sub, label + tick(dev == active_dev), 100 + i, grayed=not has_tb)
        menu_add(menu, t("m_monitor"), sub=sub, hbm=ic("monitor"))
    menu_add(menu, sep=True)
    menu_add(menu, t("m_settings"), 6, hbm=ic("settings"))
    menu_langs[:] = lang_codes()
    sub2 = user32.CreatePopupMenu()
    menu_add(sub2, t("m_lang_auto") + tick(not lang_override), 200)
    for i, code in enumerate(menu_langs):
        menu_add(sub2, lang_name(code) + tick(lang_override == code), 201 + i)
    menu_add(menu, t("m_language") + ("" if lang_code == "en" else " / Language"), sub=sub2, hbm=ic("language"))
    menu_add(menu, t("m_version", v=VERSION), grayed=True)
    menu_add(menu, sep=True)
    menu_add(menu, t("m_exit"), 2, hbm=ic("exit"))
    pt = wt.POINT(); user32.GetCursorPos(ctypes.byref(pt))
    user32.SetForegroundWindow(hwnd)
    user32.TrackPopupMenu(menu, 0x20 | 0x2 | (0x8000 if is_rtl() else 0), pt.x, pt.y, 0, hwnd, None)  # TPM_LAYOUTRTL для ar/he
    user32.PostMessageW(hwnd, 0, 0, 0)
    user32.DestroyMenu(menu)
    for h in icons:
        gdi32.DeleteObject(h)

# ---------------- вікно налаштування погоди (плоский стиль, елементи малює сама програма) ----------------
class DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [("CtlType", wt.UINT), ("CtlID", wt.UINT), ("itemID", wt.UINT), ("itemAction", wt.UINT),
                ("itemState", wt.UINT), ("hwndItem", P), ("hDC", P), ("rcItem", wt.RECT),
                ("itemData", ctypes.c_size_t)]

user32.EnableWindow.argtypes = [P, wt.BOOL]
user32.InvalidateRect.argtypes = [P, P, wt.BOOL]
user32.GetDlgItem.restype = P
user32.GetDlgItem.argtypes = [P, ctypes.c_int]

dlg_hwnd = None
dlg_ctl = {}
dlg_font = None
dlg_busy = False
dlg_dark = False
dlg_pal = {}
dlg_brushes = []   # [фон вікна, фон полів введення]
dlg_results = []   # результати пошуку, паралельні рядкам списку: (підпис, lat, lon, коротка назва)
dlg_pending = []   # результат фонового пошуку
dlg_sel = {"loc": 0, "units": 0, "theme": 0}   # вибір у "сегментах"
SEG = {111: ("loc", 0), 112: ("loc", 1), 121: ("units", 0), 122: ("units", 1),
       131: ("theme", 0), 132: ("theme", 1), 133: ("theme", 2)}

def dlg_palette(dark):
    if dark:
        return dict(bg=(32, 32, 32), edit=(45, 45, 45), btn=(58, 58, 58), btn_press=(78, 78, 78),
                    seg_sel=(84, 84, 84), text=(240, 240, 240), dim=(125, 125, 125),
                    accent=(76, 194, 255), accent_text=(0, 0, 0), list_sel=(70, 70, 70))
    return dict(bg=(243, 243, 243), edit=(255, 255, 255), btn=(225, 225, 225), btn_press=(205, 205, 205),
                seg_sel=(255, 255, 255), text=(26, 26, 26), dim=(150, 150, 150),
                accent=(0, 103, 192), accent_text=(255, 255, 255), list_sel=(204, 228, 247))

def _free_dlg_theme():
    global dlg_dark
    for b in dlg_brushes:
        gdi32.DeleteObject(b)
    dlg_brushes.clear()
    dlg_dark = False

def read_edit(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, buf, 256)
    return buf.value

def lb_reset(h):
    user32.SendMessageW(h, 0x184, 0, 0)  # LB_RESETCONTENT

def lb_add(h, text):
    buf = ctypes.create_unicode_buffer(text)
    user32.SendMessageW(h, 0x180, 0, ctypes.addressof(buf))  # LB_ADDSTRING

def lb_sel(h, i):
    user32.SendMessageW(h, 0x186, i, 0)  # LB_SETCURSEL

def lb_get(h):
    return ctypes.c_int(user32.SendMessageW(h, 0x188, 0, 0)).value  # LB_GETCURSEL

def lb_text(h, i):
    buf = ctypes.create_unicode_buffer(300)
    user32.SendMessageW(h, 0x189, i, ctypes.addressof(buf))  # LB_GETTEXT
    return buf.value

def dlg_redraw_group(hwnd, grp):
    for cid, (g, _) in SEG.items():
        if g == grp:
            h = user32.GetDlgItem(hwnd, cid)
            if h:
                user32.InvalidateRect(h, None, True)

def dlg_update_enabled():
    manual = dlg_sel["loc"] == 1
    for k in ("search", "btn", "res"):
        user32.EnableWindow(dlg_ctl[k], manual)
        user32.InvalidateRect(dlg_ctl[k], None, True)

def dlg_search_job(text, lang):
    global dlg_pending
    try:
        dlg_pending = geocode(text, lang)
    except Exception:
        dlg_pending = []
    if dlg_hwnd:
        user32.PostMessageW(dlg_hwnd, WM_DLG_SEARCH, 0, 0)

def dlg_start_search():
    text = read_edit(dlg_ctl["search"]).strip()
    if not text:
        return
    lang = lang_code.split("-")[0] if lang_code else "en"
    user32.EnableWindow(dlg_ctl["btn"], False)
    user32.InvalidateRect(dlg_ctl["btn"], None, True)
    threading.Thread(target=dlg_search_job, args=(text, lang), daemon=True).start()

def dlg_show_results():
    dlg_results[:] = list(dlg_pending)
    lb_reset(dlg_ctl["res"])
    if dlg_results:
        for lbl, *_ in dlg_results:
            lb_add(dlg_ctl["res"], lbl)
        lb_sel(dlg_ctl["res"], 0)
        dlg_sel["loc"] = 1  # знайшли - одразу режим "вручну"
        dlg_redraw_group(dlg_hwnd, "loc")
    else:
        lb_add(dlg_ctl["res"], t("d_not_found"))
    dlg_update_enabled()

def dlg_save():
    idx = lb_get(dlg_ctl["res"])
    if dlg_sel["loc"] == 1 and 0 <= idx < len(dlg_results):
        _, lat, lon, short = dlg_results[idx]
        cfg.update(loc_mode="manual", m_name=short, m_lat=repr(float(lat)), m_lon=repr(float(lon)))
    else:
        cfg["loc_mode"] = "auto"
    cfg["units"] = "f" if dlg_sel["units"] == 1 else "c"
    m = re.search(r"\d+", read_edit(dlg_ctl["interval"]))
    cfg["interval"] = min(180, max(5, int(m.group()))) if m else 15
    cfg["theme"] = dlg_sel["theme"]
    save_cfg()
    with lock:
        state["cur"] = None
    wake.set()
    user32.DestroyWindow(dlg_hwnd)
    widgets_update(force=True)

def _fill(hdc, rc, color):
    br = gdi32.CreateSolidBrush(rgb(*color))
    user32.FillRect(hdc, ctypes.byref(rc), br)
    gdi32.DeleteObject(br)

def _text(hdc, rc, text, color, flags, pad=0):
    r = wt.RECT(rc.left + pad, rc.top, rc.right - pad, rc.bottom)
    gdi32.SetBkMode(hdc, 1)
    gdi32.SetTextColor(hdc, rgb(*color))
    user32.DrawTextW(hdc, text, -1, ctypes.byref(r), flags)

def dlg_draw_item(dis):
    pal, sc = dlg_pal, get_scale()
    hdc = dis.hDC
    old = gdi32.SelectObject(hdc, dlg_font)
    rc = dis.rcItem
    disabled = bool(dis.itemState & 0x4)   # ODS_DISABLED
    pressed = bool(dis.itemState & 0x1)    # ODS_SELECTED
    if dis.CtlType == 2:  # список результатів
        if dis.itemID != 0xFFFFFFFF:
            _fill(hdc, rc, pal["list_sel"] if (pressed and not disabled) else pal["edit"])
            _text(hdc, rc, lb_text(dis.hwndItem, dis.itemID), pal["dim"] if disabled else pal["text"],
                  0x4 | 0x20 | 0x8000 | 0x800, pad=int(8 * sc))
    else:                 # кнопки
        cid = dis.CtlID
        label = read_edit(dis.hwndItem)
        if cid in SEG:
            grp, idx = SEG[cid]
            sel = dlg_sel[grp] == idx
            _fill(hdc, rc, pal["btn_press"] if pressed else (pal["seg_sel"] if sel else pal["btn"]))
            if sel:
                _fill(hdc, wt.RECT(rc.left, rc.bottom - max(2, int(2 * sc)), rc.right, rc.bottom), pal["accent"])
            col = pal["text"]
        elif cid == 1:    # "Зберегти" - акцентна кнопка
            _fill(hdc, rc, pal["accent"])
            col = pal["accent_text"]
        else:
            _fill(hdc, rc, pal["btn_press"] if pressed else pal["btn"])
            col = pal["dim"] if disabled else pal["text"]
        _text(hdc, rc, label, col, 0x1 | 0x4 | 0x20 | 0x800)
    gdi32.SelectObject(hdc, old)

def dlg_proc(hwnd, msg, wparam, lparam):
    global dlg_hwnd, dlg_font
    if dlg_brushes:
        if msg == 0x14:  # WM_ERASEBKGND - фон вікна
            rc = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rc))
            user32.FillRect(wparam, ctypes.byref(rc), dlg_brushes[0])
            return 1
        if msg == 0x138:  # WM_CTLCOLORSTATIC - підписи, а також заблоковані поля введення
            if dlg_ctl and lparam == dlg_ctl.get("search"):
                gdi32.SetTextColor(wparam, rgb(*dlg_pal["dim"]))
                gdi32.SetBkColor(wparam, rgb(*dlg_pal["edit"]))
                return dlg_brushes[1]
            gdi32.SetTextColor(wparam, rgb(*dlg_pal["text"]))
            gdi32.SetBkColor(wparam, rgb(*dlg_pal["bg"]))
            return dlg_brushes[0]
        if msg == 0x133:  # WM_CTLCOLOREDIT - поля введення
            gdi32.SetTextColor(wparam, rgb(*dlg_pal["text"]))
            gdi32.SetBkColor(wparam, rgb(*dlg_pal["edit"]))
            return dlg_brushes[1]
        if msg == 0x134:  # WM_CTLCOLORLISTBOX - порожнє місце списку
            return dlg_brushes[1]
    if msg == 0x2B:  # WM_DRAWITEM
        dlg_draw_item(ctypes.cast(lparam, ctypes.POINTER(DRAWITEMSTRUCT)).contents)
        return 1
    if msg == WM_DLG_SEARCH:
        dlg_show_results()
        return 0
    if msg == 0x111:  # WM_COMMAND
        cid, code = wparam & 0xFFFF, (wparam >> 16) & 0xFFFF
        if cid == 1 and code == 0:
            dlg_save()
        elif cid == 2 and code == 0:
            user32.DestroyWindow(hwnd)
        elif cid == 103 and code == 0:
            dlg_start_search()
        elif cid in SEG and code == 0:
            grp, idx = SEG[cid]
            dlg_sel[grp] = idx
            dlg_redraw_group(hwnd, grp)
            if grp == "loc":
                dlg_update_enabled()
        return 0
    if msg == 0x400:  # DM_GETDEFID - кнопка за замовчуванням (Enter)
        return (0x534B << 16) | 1
    if msg == 0x10:  # WM_CLOSE
        user32.DestroyWindow(hwnd)
        return 0
    if msg == 0x2:  # WM_DESTROY
        if dlg_font:
            gdi32.DeleteObject(dlg_font)
        dlg_font = None
        dlg_hwnd = None
        dlg_ctl.clear()
        _free_dlg_theme()
        for ih in dlg_icons:
            user32.DestroyIcon(ih)
        dlg_icons.clear()
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

_dlg_proc_ref = WNDPROC(dlg_proc)

def open_settings_dialog():
    global dlg_hwnd, dlg_font, dlg_busy, dlg_dark, dlg_pal
    if dlg_hwnd and user32.IsWindow(dlg_hwnd):
        user32.ShowWindow(dlg_hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(dlg_hwnd)
        return
    sc = get_scale()
    S = lambda v: int(round(v * sc))
    cw = S(500)
    dlg_font = gdi32.CreateFontW(-S(13), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")
    y0 = S(18)
    Y_LOC, Y_SRCH, Y_LIST = y0, y0 + S(42), y0 + S(84)
    LIST_H = S(104)
    Y_UNITS = Y_LIST + LIST_H + S(14)
    Y_INT, Y_THEME = Y_UNITS + S(42), Y_UNITS + S(84)
    by = Y_THEME + S(56)
    ch = by + S(32) + S(18)
    style = 0x00C00000 | 0x00080000  # WS_CAPTION | WS_SYSMENU
    rc = wt.RECT(0, 0, cw, ch)
    user32.AdjustWindowRectEx(ctypes.byref(rc), style, False, 0x8)
    w, h = rc.right - rc.left, rc.bottom - rc.top
    sx, sy = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    dark = not light_theme()
    apply_menu_theme()
    dlg_pal = dlg_palette(dark)
    dlg_brushes[:] = [gdi32.CreateSolidBrush(rgb(*dlg_pal["bg"])), gdi32.CreateSolidBrush(rgb(*dlg_pal["edit"]))]
    dlg_dark = dark
    dlg_busy = True
    hw = user32.CreateWindowExW(0x8 | (0x400000 if is_rtl() else 0), "WeatherTraySettings", t("d_title"), style,
                                (sx - w) // 2, (sy - h) // 2, w, h, None, None, HINST, None)
    if not hw:
        dlg_busy = False
        gdi32.DeleteObject(dlg_font)
        dlg_font = None
        _free_dlg_theme()
        return
    dlg_hwnd = hw
    if dark:  # темний заголовок вікна
        try:
            val = ctypes.c_int(1)
            if dwmapi.DwmSetWindowAttribute(hw, 20, ctypes.byref(val), 4) != 0:
                dwmapi.DwmSetWindowAttribute(hw, 19, ctypes.byref(val), 4)
        except Exception:
            pass
    for kind, metric in ((1, 11), (0, 49)):
        ih = load_icon(user32.GetSystemMetrics(metric))
        if ih:
            dlg_icons.append(ih)
            user32.SendMessageW(hw, 0x80, kind, ih)  # WM_SETICON
    kids = []
    def mk(cls, text, st, ex, x, y, ww, hh, cid=0):
        c = user32.CreateWindowExW(ex, cls, text, 0x40000000 | 0x10000000 | st,
                                   x, y, ww, hh, hw, cid, HINST, None)
        kids.append(c)
        return c
    OWNER = 0x10000 | 0xB   # WS_TABSTOP | BS_OWNERDRAW
    lx, cx0 = S(20), S(190)
    cwid = cw - cx0 - S(20)
    lab = lambda txt, y, hh=S(30): mk("STATIC", txt, 0x200, 0, lx, y, S(165), hh)  # SS_CENTERIMAGE
    seg = lambda labels, ids, y: [mk("BUTTON", lab_, OWNER, 0, cx0 + i * (cwid // len(labels)), y,
                                     cwid // len(labels) - S(4), S(30), cid)
                                  for i, (lab_, cid) in enumerate(zip(labels, ids))]

    lab(t("d_loc"), Y_LOC)
    seg([t("d_loc_auto"), t("d_loc_manual")], (111, 112), Y_LOC)
    lab(t("d_search_label"), Y_SRCH)
    dlg_ctl["search"] = mk("EDIT", "", 0x10000 | 0x80, 0, cx0, Y_SRCH + S(2), cwid - S(100), S(26), 102)
    dlg_ctl["btn"] = mk("BUTTON", t("d_search"), OWNER, 0, cx0 + cwid - S(92), Y_SRCH, S(92), S(30), 103)
    # список результатів: LBS_NOTIFY | OWNERDRAWFIXED | HASSTRINGS | NOINTEGRALHEIGHT, WS_VSCROLL
    dlg_ctl["res"] = mk("LISTBOX", "", 0x10000 | 0x200000 | 0x1 | 0x10 | 0x40 | 0x100, 0,
                        cx0, Y_LIST, cwid, LIST_H, 104)
    lab(t("d_units"), Y_UNITS)
    seg(["\u00b0C", "\u00b0F"], (121, 122), Y_UNITS)
    lab(t("d_interval"), Y_INT)
    dlg_ctl["interval"] = mk("EDIT", str(cfg["interval"]), 0x10000 | 0x80 | 0x2000, 0,  # ES_NUMBER
                             cx0, Y_INT + S(2), S(80), S(26), 106)
    lab(t("d_theme"), Y_THEME)
    seg([t("d_theme_sys"), t("d_theme_dark"), t("d_theme_light")], (131, 132, 133), Y_THEME)
    bx = cw - S(20) - S(110)
    mk("BUTTON", t("d_save"), OWNER, 0, bx - S(10) - S(110), by, S(110), S(34), 1)
    mk("BUTTON", t("d_cancel"), OWNER, 0, bx, by, S(110), S(34), 2)
    for c in kids:
        user32.SendMessageW(c, 0x30, dlg_font, 1)  # WM_SETFONT
    user32.SendMessageW(dlg_ctl["res"], 0x1A0, 0, S(26))  # LB_SETITEMHEIGHT
    for k in ("search", "interval"):  # відступи тексту в полях введення
        user32.SendMessageW(dlg_ctl[k], 0xD3, 3, S(7) | (S(7) << 16))  # EM_SETMARGINS

    dlg_sel["loc"] = 1 if (cfg["loc_mode"] == "manual" and cfg["m_lat"] != "") else 0
    dlg_sel["units"] = 1 if cfg["units"] == "f" else 0
    dlg_sel["theme"] = cfg["theme"] if 0 <= cfg["theme"] <= 2 else 0
    dlg_results[:] = []
    if cfg["m_lat"] != "" and cfg["m_name"]:
        try:
            dlg_results.append((cfg["m_name"], float(cfg["m_lat"]), float(cfg["m_lon"]), cfg["m_name"]))
            lb_add(dlg_ctl["res"], cfg["m_name"])
            lb_sel(dlg_ctl["res"], 0)
        except ValueError:
            pass
    dlg_update_enabled()

    if dark:  # темні смуги прокрутки списку й поля введення
        try:
            uxtheme.SetWindowTheme(dlg_ctl["res"], "DarkMode_Explorer", None)
            for k in ("search", "interval"):
                uxtheme.SetWindowTheme(dlg_ctl[k], "DarkMode_CFD", None)
        except Exception:
            pass
    user32.SendMessageW(hw, 0x128, 1 | (1 << 16), 0)  # WM_UPDATEUISTATE: без пунктирних рамок фокуса
    dlg_busy = False
    user32.ShowWindow(hw, 5)
    user32.SetForegroundWindow(hw)

def widget_proc(hwnd, msg, wparam, lparam):
    global offset_dp
    if msg == 0x201:  # WM_LBUTTONDOWN - початок перетягування
        hide_tip()
        pt = wt.POINT(); user32.GetCursorPos(ctypes.byref(pt))
        drag.update(active=True, x0=pt.x, off0=offset_dp, moved=False)
        applied["px"] = int(offset_dp * get_scale())
        user32.SetCapture(hwnd)
        return 0
    if msg == 0x200 and drag["active"]:  # WM_MOUSEMOVE
        pt = wt.POINT(); user32.GetCursorPos(ctypes.byref(pt))
        dx = drag["x0"] - pt.x
        if abs(dx) > 3 and not locked:
            drag["moved"] = True
        if drag["moved"]:
            offset_dp = max(0, int(drag["off0"] + dx / get_scale()))
            layout()
        return 0
    if msg == 0x200:  # WM_MOUSEMOVE без перетягування - чекаємо наведення (400 мс) для підказки
        tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 0x1 | 0x2, hwnd, 400)  # TME_HOVER | TME_LEAVE
        user32.TrackMouseEvent(ctypes.byref(tme))
        return 0
    if msg == 0x2A1:  # WM_MOUSEHOVER
        w = widgets.get(hwnd)
        if w and not drag["active"]:
            show_tip(w)
        return 0
    if msg == 0x2A3:  # WM_MOUSELEAVE
        hide_tip(widgets.get(hwnd))
        return 0
    if msg == 0x202:  # WM_LBUTTONUP
        if drag["active"]:
            drag["active"] = False
            user32.ReleaseCapture()
            if drag["moved"]:
                reg_set(offset_key(active_dev), offset_dp)
            # звичайний лівий клік нічого не робить - меню відкривається лише правою кнопкою
        return 0
    if msg == 0x205:  # WM_RBUTTONUP
        hide_tip()
        if hwnd_main:
            show_menu(hwnd_main)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

_widget_proc_ref = WNDPROC(widget_proc)

def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x113 and wparam == 2:  # WM_TIMER 2 - швидка перевірка накладання з сусідами
        peer_tick(wx)
        return 0
    if msg == WM_APP_UPDATE or msg == 0x113:  # WM_TIMER
        refresh(hwnd)
        return 0
    if msg == 0x111:  # WM_COMMAND
        cid = wparam & 0xFFFF
        if cid == 1:
            set_autostart(not autostart_on())
        elif cid == 3:
            wake.set()
        elif cid == 5:
            toggle_lock()
        elif cid == 6:
            open_settings_dialog()
        elif cid == 7:
            reset_position()
        elif 100 <= cid < 200:
            select_monitor(cid - 100)
        elif 200 <= cid < 400:
            select_language(cid - 200)
        elif cid == 2:
            os._exit(0)
        return 0
    if taskbar_created and msg == taskbar_created:  # explorer перезапущено
        recreate_widgets()
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

_wndproc_ref = WNDPROC(wndproc)

def main():
    global hwnd_main, taskbar_created, HINST, monitor_dev, locked
    try:  # чіткий віджет на екранах з масштабуванням
        user32.SetProcessDpiAwarenessContext.argtypes = [P]
        user32.SetProcessDpiAwarenessContext(P(-4))  # PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass
    k32.CreateMutexW(None, False, "Local\\WeatherTrayMutex")
    if ctypes.get_last_error() == 183:  # вже запущено
        return
    first_run_autostart()
    load_cfg()
    load_external_langs()
    set_language(reg_get_str("language", ""))  # мова: збережений вибір або мова Windows
    monitor_dev = reg_get_str("monitor", "")
    locked = bool(reg_get("locked", 0))
    taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
    HINST = k32.GetModuleHandleW(None)

    wc = WNDCLASSW()
    wc.lpfnWndProc = _wndproc_ref
    wc.hInstance = HINST
    wc.lpszClassName = "WeatherTrayWnd"
    user32.RegisterClassW(ctypes.byref(wc))

    wc2 = WNDCLASSW()
    wc2.lpfnWndProc = _widget_proc_ref
    wc2.hInstance = HINST
    wc2.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
    wc2.lpszClassName = "WeatherTrayWidget"
    user32.RegisterClassW(ctypes.byref(wc2))

    wc3 = WNDCLASSW()
    wc3.lpfnWndProc = _dlg_proc_ref
    wc3.hInstance = HINST
    wc3.hCursor = user32.LoadCursorW(None, 32512)
    wc3.hbrBackground = 16  # COLOR_BTNFACE + 1
    wc3.lpszClassName = "WeatherTraySettings"
    user32.RegisterClassW(ctypes.byref(wc3))

    wc4 = WNDCLASSW()
    wc4.lpfnWndProc = _tip_proc_ref
    wc4.hInstance = HINST
    wc4.lpszClassName = "WeatherTrayTip"
    user32.RegisterClassW(ctypes.byref(wc4))

    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, APP, 0, 0, 0, 0, 0, None, None, HINST, None)
    hwnd_main = hwnd
    refresh(hwnd)
    user32.SetTimer(hwnd, 1, 5000, None)
    user32.SetTimer(hwnd, 2, 1000, None)
    threading.Thread(target=weather_loop, daemon=True).start()
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if dlg_hwnd and user32.IsDialogMessageW(dlg_hwnd, ctypes.byref(msg)):
            continue
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

if __name__ == "__main__":
    main()
