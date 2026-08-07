"""Make the Win32 core importable in tests, whatever the file is called.

The core lives in a `.pyw` so double-clicking it does not open a console, and
Python does not import `.pyw` by name. It has also been renamed once already
(`SAISENT_GUI.pyw` -> `SAISENT_core.pyw`), which broke every test that said
`import SAISENT_GUI` at collection time.

So: find whichever file is actually there, load it once, and register it under
both names. A rename now costs one entry in `CORE_FILENAMES` instead of a red
suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE_FILENAMES = ("SAISENT_core.pyw",)
CORE_ALIASES = ("saisent_gui_core", "SAISENT_GUI", "SAISENT_core")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_core():
    for name in CORE_FILENAMES:
        path = ROOT / name
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(CORE_ALIASES[0], path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        # Registered before exec so a self-import inside the core resolves.
        for alias in CORE_ALIASES:
            sys.modules.setdefault(alias, module)
        spec.loader.exec_module(module)
        for alias in CORE_ALIASES:
            sys.modules[alias] = module
        return module
    return None


_load_core()
