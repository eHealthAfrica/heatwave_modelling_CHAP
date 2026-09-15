"""heatwave package. Stubs out `blessings` before any submodule (or geemap) can import it."""
import sys
import types

sys.modules.setdefault("blessings", types.ModuleType("blessings"))
