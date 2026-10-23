import sys

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "linux_only: needs Linux pidfd, SCM_CREDENTIALS, /proc or 108-byte AF_UNIX paths")


def pytest_collection_modifyitems(config, items):
    if sys.platform == "linux":
        return
    # Development Macs lack these kernel interfaces; CI runs every marked test on Linux.
    skip = pytest.mark.skip(reason="requires Linux kernel interfaces; covered by Linux CI")
    for item in items:
        if "linux_only" in item.keywords:
            item.add_marker(skip)
