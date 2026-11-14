"""Show the startup card when launching the portable Windows release."""
import builtins
from pathlib import Path
import sys

from startup_splash import StartupSplash

check_modes = ('--smoke-test', '--check-data', '--native-runtime-check')
if '--startup-self-test' in sys.argv or not any(mode in sys.argv for mode in check_modes):
    try:
        card = Path(sys._MEIPASS) / 'startup_card.bmp'
        splash = StartupSplash(str(card)).start()
        splash.update(.95)
        builtins._optical_startup_splash = splash
    except Exception:
        # The application can still run if the startup card is unavailable.
        pass
