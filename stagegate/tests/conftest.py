"""Shared test setup. The network block applies to EVERY test file: any real HTTP call fails the test.

The only transport in stagegate is urllib.request.urlopen (stagegate.clappia.urllib_transport).
A test that needs to exercise that transport monkeypatches urlopen itself, which overrides this block
for that test only.
"""
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("real network call attempted in tests")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
