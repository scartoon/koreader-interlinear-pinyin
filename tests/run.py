#!/usr/bin/env python3
"""Run the pure-Lua tests under LuaJIT (the Lua KOReader uses).

    pip install lupa
    python3 tests/run.py
"""
import os
import sys

from lupa.luajit21 import LuaRuntime

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plugin = os.path.join(root, "interlinearpinyin.koplugin")

lua = LuaRuntime(unpack_returned_tuples=True)
lua.globals().PLUGIN_DIR = plugin
lua.execute(f'package.path = "{plugin}/?.lua;" .. package.path')
try:
    for name in ("test_resolve.lua", "test_page.lua"):
        lua.execute(open(os.path.join(root, "tests", name), encoding="utf-8").read())
except Exception as e:  # noqa: BLE001
    print(e)
    sys.exit(1)
