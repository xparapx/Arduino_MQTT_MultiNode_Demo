"""The aq package skeleton imports cleanly and exposes the planned modules."""

import importlib

import aq


def test_all_modules_import():
    for name in aq.__all__:
        mod = importlib.import_module(f"aq.{name}")
        assert mod.__doc__, f"aq.{name} needs a module docstring"


def test_regime_names_fixed():
    from aq.regime import REGIMES

    assert REGIMES == ("clean", "matter", "human", "mixed")
