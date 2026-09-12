"""Run pytest-style test modules under the stdlib runner.

CI is `python -m unittest discover` on a stdlib-only interpreter
(.github/workflows/tests.yml) and that is a property worth keeping: the
suite runs anywhere with nothing installed. Six modules written on
2026-09-11/12 were pytest-style -- module-level `test_*` functions,
`pytest.approx`, `pytest.raises` -- so unittest could not import them and
CI was red from 05:00Z until this landed, while the same files passed
under pytest on the developer machine.

This module is the bridge. It provides the two pytest helpers those files
use, and `as_test_case`, which turns a module's `test_*` functions into a
TestCase the stdlib loader can find. Under pytest it returns None so the
functions are not collected twice.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import pathlib
import re
import sys
import tempfile
import unittest


class _Approx:
    """`x == approx(y)`, with pytest's defaults: rel 1e-6, abs 1e-12."""

    def __init__(self, expected, rel=1e-6, abs=1e-12):
        self.expected = expected
        self.rel = rel
        self.abs = abs

    def __eq__(self, actual):
        try:
            return abs(actual - self.expected) <= max(
                self.abs, self.rel * abs(self.expected))
        except TypeError:
            return False

    def __ne__(self, actual):
        return not self.__eq__(actual)

    def __repr__(self):
        return f"approx({self.expected!r})"


def approx(expected, rel=1e-6, abs=1e-12):
    return _Approx(expected, rel=rel, abs=abs)


@contextlib.contextmanager
def raises(exc, match=None):
    """`with raises(ValueError, match="floor"):` -- fails if nothing is
    raised, or the wrong thing, or the message does not match."""
    try:
        yield
    except exc as caught:
        if match is not None and not re.search(match, str(caught)):
            raise AssertionError(
                f"{exc.__name__} raised but {match!r} not in {str(caught)!r}")
        return
    raise AssertionError(f"{exc.__name__} was not raised")


class _MonkeyPatch:
    """The slice of pytest's `monkeypatch` these modules use, undone in
    reverse order when the test ends."""

    def __init__(self):
        self._undo = []

    def chdir(self, path):
        previous = os.getcwd()
        os.chdir(str(path))
        self._undo.append(lambda: os.chdir(previous))

    def setattr(self, target, name, value):
        previous = getattr(target, name)
        setattr(target, name, value)
        self._undo.append(lambda: setattr(target, name, previous))

    def setitem(self, mapping, key, value):
        missing = object()
        previous = mapping.get(key, missing)
        mapping[key] = value

        def restore():
            if previous is missing:
                mapping.pop(key, None)
            else:
                mapping[key] = previous
        self._undo.append(restore)

    def setenv(self, name, value):
        self.setitem(os.environ, name, str(value))

    def delenv(self, name, raising=True):
        if name in os.environ:
            previous = os.environ[name]
            del os.environ[name]
            self._undo.append(lambda: os.environ.__setitem__(name, previous))
        elif raising:
            raise KeyError(name)

    def undo(self):
        while self._undo:
            self._undo.pop()()


def _call_with_fixtures(function):
    """Call a test function, supplying the two pytest fixtures these
    modules use: `tmp_path` (a fresh directory) and `monkeypatch`."""
    wanted = [p.name for p in inspect.signature(function).parameters.values()
              if p.default is inspect.Parameter.empty]
    unknown = [w for w in wanted if w not in ("tmp_path", "monkeypatch")]
    if unknown:
        raise TypeError(f"{function.__name__} wants fixtures the bridge does "
                        f"not provide: {unknown}")
    kwargs = {}
    patch = None
    with tempfile.TemporaryDirectory() as tmp:
        if "tmp_path" in wanted:
            kwargs["tmp_path"] = pathlib.Path(tmp)
        if "monkeypatch" in wanted:
            patch = _MonkeyPatch()
            kwargs["monkeypatch"] = patch
        try:
            function(**kwargs)
        finally:
            if patch is not None:
                patch.undo()


def as_test_case(namespace, name="FunctionTests"):
    """A TestCase whose methods call the module's `test_*` functions.

    Returns None under pytest, which collects the functions itself and
    would otherwise run each test twice."""
    if "pytest" in sys.modules:
        return None
    functions = {key: value for key, value in namespace.items()
                 if key.startswith("test_") and callable(value)
                 and not isinstance(value, type)}
    methods = {}
    for key, function in functions.items():
        def method(self, _function=function):
            _call_with_fixtures(_function)
        method.__name__ = key
        method.__doc__ = function.__doc__
        methods[key] = method
    return type(name, (unittest.TestCase,), methods)
