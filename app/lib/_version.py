"""Single-source version resolver for kdkvm.

The authoritative version lives in ``app/web/version.json``. This module
exposes that value as ``__version__`` so setuptools can read it via
``[tool.setuptools.dynamic] version = { attr = "lib._version.__version__" }``.

Reading at import time is intentional — setuptools invokes this during build
and pip install, so the JSON file must be present in the source tree (it is).
If the JSON is missing or malformed we fail loudly rather than shipping an
unknown version: a silent "0.0.0" would defeat the purpose of unifying the
version source.
"""
from __future__ import annotations

import json
from pathlib import Path

_VERSION_JSON = Path(__file__).resolve().parent.parent / "web" / "version.json"

with _VERSION_JSON.open("r", encoding="utf-8") as _f:
    _payload = json.load(_f)

__version__: str = _payload["version"]
__build__: str = _payload.get("build", "")
__codename__: str = _payload.get("codename", "")
