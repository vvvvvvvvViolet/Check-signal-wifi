CHECK SIGNAL WIFI
=================

WiFi survey and diagnosis for factory and warehouse networks.


HOW TO RUN
----------

Windows:  double-click CheckSignalWiFi.exe
macOS:    right-click CheckSignalWiFi -> Open (see "First run on macOS" below)
Linux:    chmod +x CheckSignalWiFi, then ./CheckSignalWiFi

A console window opens and your browser is sent to the app automatically.
Nothing needs to be installed first - no Python, no Node.js.

To stop the app, close the console window.


FIRST RUN ON WINDOWS
--------------------

Windows SmartScreen may warn that the publisher is unknown, because this
executable is not code-signed. Click "More info" then "Run anyway".


FIRST RUN ON MACOS
------------------

macOS blocks unsigned apps on a plain double-click. Right-click the file,
choose "Open", then confirm. This is only needed the first time.


ARE THE READINGS REAL?
----------------------

The console window says which source it is using. If it prints

    !! No WiFi tooling found on this machine, so readings are SIMULATED

then no real radio is being read - the app is generating plausible data so the
interface can still be explored. Simulated readings are clearly labelled
throughout the app. Do not use them in a report.

For real readings the machine needs its platform's WiFi tooling:

    Windows   netsh          (built in, nothing to do)
    Linux     nmcli or iw
    macOS     airport        (removed in newer macOS versions)

On macOS the BSSID is hidden unless the app is granted Location Services
permission - that is an operating system rule, not an app setting.


WHERE YOUR DATA IS KEPT
-----------------------

Survey points, floor plans and test history are stored per user, so they
survive replacing the executable with a newer one:

    Windows   %LOCALAPPDATA%\CheckSignalWiFi
    macOS     ~/Library/Application Support/CheckSignalWiFi
    Linux     ~/.local/share/CheckSignalWiFi

The console window prints the exact path at startup. Back up that folder to
keep your surveys; delete it to start clean.


OPTIONS
-------

    CheckSignalWiFi --port 9000     use a different port
    CheckSignalWiFi --no-browser    start without opening a browser

If the default port is already taken by another program, the app picks a free
one and prints it. Launching a second time while it is already running just
reopens the browser instead of starting a duplicate.


TROUBLESHOOTING
---------------

The window flashes and disappears
    Open a terminal in this folder and run the program from there so the error
    stays visible.

The browser did not open
    Use the address printed in the console window, usually
    http://127.0.0.1:8000

"Not connected to any WiFi network" while the internet works
    Check the console window for the WiFi source. If it reads "mock", the
    machine has no WiFi tooling the app can read.
