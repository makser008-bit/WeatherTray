Weather Tray - version 0.4.4
============================
Українська версія: README.txt


ABOUT
-----
Weather Tray is a small Windows 11 program that shows the current weather right on the taskbar,
next to the system tray:

    [cloud 3°] ^

The location is detected automatically (geolocation). It runs in the background, starts with Windows
and follows the Windows theme (dark/light), the system language and the display scale. The widget is
built the same way as in X11 Battery: a transparent child window of the taskbar itself, so it never
overlaps fullscreen games or other windows, and the interface is styled like Windows 11.


WHAT IT SHOWS
-------------
WIDGET - a weather icon (clear, partly cloudy, cloudy, fog, rain, snow, thunderstorm; day and night)
and the temperature, e.g. "3°". The text color follows the Windows theme.

TOOLTIP on hover (after ~0.4 s, drawn by the program: rounded, no white border, follows the theme):
temperature and conditions, city, feels-like, wind and humidity.


MENU (right-click the widget; a left click does nothing)
--------------------------------------------------------
Current weather and city (gray), Refresh now, Start with Windows, Lock position, Reset position,
Monitor for the widget (when there are several monitors), Weather settings..., Language, Version, Exit.


WIDGET POSITION
---------------
The widget sits to the left of the tray. Drag it with the left mouse button along the taskbar (unless
the position is locked). It never goes over the tray/clock or past the edge of the taskbar. The offset
is remembered per monitor. If other widgets (e.g. X11 Battery) are already there, just move this one.


SETTINGS
--------
  * Location: "Automatic (geolocation)" or "Manual": search cities, villages, city districts or enter
    coordinates such as 47.91, 33.39 (OpenStreetMap search).
  * Units: C or F.   * Refresh: 5-180 minutes.   * Theme: follow Windows (default), dark or light.

Automatic geolocation uses your IP address, so it is approximate (VPN / mobile networks may differ);
pick a city manually in that case. No default city is hardcoded; a city is stored only on your PC,
in the registry, when you choose one manually. All settings live in HKCU\Software\WeatherTray.


LANGUAGES
---------
Detected from Windows. Built in: Ukrainian and English. Add your own with lang\xx.json (see
lang\_template.json), then restart.


BUILD
-----
Run build_exe.bat -> WeatherTray.exe. Only Python 3 is needed (pure ctypes, no libraries).
On problems check weather_tray.log next to the program.


CHANGES
-------
0.4.0 - rewritten on the X11 Battery widget engine (taskbar child window, custom drawing, custom
        tooltip, Windows 11 menu, registry settings, lang\xx.json). Versions 0.1-0.3 used Qt.
0.4.3 - The Weather Tray, Load Tray and X11 Battery widgets no longer overlap: while dragging, a widget
        stops at its neighbour and cannot jump over it, and a small gap is kept between widgets.
0.4.4 - The gap between widgets of different programs is 4 dp, like inside X11 Battery (they look like one
        program). A widget can be placed in front of or behind a neighbour: when you drag past the
        neighbour's middle it hops to the other side, but never lies on top of it. After switching
        monitors, starting, or an Explorer restart, the widget that appeared moves away from those
        already in place; overlap is checked every second.
