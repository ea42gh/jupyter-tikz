from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable

_CACHE_MAXSIZE = int(os.environ.get("JUPYTER_TIKZ_CACHE_SIZE", "64"))
_CACHE: "OrderedDict[tuple[str, str, str, bool, bool, bool, str], str]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_render_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def get_or_render_base_svg(
    key: tuple[str, str, str, bool, bool, bool, str],
    render: Callable[[], str],
) -> str:
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]

    svg = render()

    with _CACHE_LOCK:
        _CACHE[key] = svg
        _CACHE.move_to_end(key)
        while len(_CACHE) > max(0, _CACHE_MAXSIZE):
            _CACHE.popitem(last=False)
    return svg
