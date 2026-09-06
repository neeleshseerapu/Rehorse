"""Shared logic for the Rehorse scripts, imported as `from rehorse_lib import <module>`.

A script Claude Code invokes as a hook stays under 150 lines: a guarantee nobody reads whole is not a guarantee, and
a hook is the only thing standing between the model and the user's branch. That cap counts the entry script — the file
named in hooks/hooks.json — and the logic it needs may live here instead of being squeezed into it or dropped.

Same constraints as the entry scripts otherwise: Python 3 standard library only and no install step. This package is
importable because the entry script's own directory is on sys.path, so `scripts/verify.py` finds `scripts/rehorse_lib/`
with no path juggling, no `-m`, and no packaging. Nothing here writes state except through `state.save`.
"""
