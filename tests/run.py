#!/usr/bin/env python3
"""Run the pure-Lua tests under LuaJIT (the Lua KOReader uses).

    pip install lupa
    python3 tests/run.py
"""
import os
import sys

try:
    from lupa.luajit21 import LuaRuntime
    RUNTIME = "LuaJIT 2.1"
except ImportError:
    # Some lupa wheels (e.g. macOS arm64) ship without LuaJIT. LuaJIT
    # implements Lua 5.1, so that is the closest stand-in.
    from lupa.lua51 import LuaRuntime
    RUNTIME = "Lua 5.1 (LuaJIT not available in this lupa build)"
print(f"Running tests under {RUNTIME}")

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plugin = os.path.join(root, "interlinearpinyin.koplugin")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().PLUGIN_DIR = plugin
lua.execute(f'package.path = "{plugin}/?.lua;" .. package.path')
try:
    for name in ("test_resolve.lua", "test_page.lua", "test_layout.lua", "test_hit.lua", "test_defs.lua",
                 "test_menu.lua", "test_special.lua"):
        lua.execute(open(os.path.join(root, "tests", name), encoding="utf-8").read())
except Exception as e:  # noqa: BLE001
    print(e)
    sys.exit(1)
