"""Shared pytest configuration and fixtures."""
import pytest


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests in tests/hardware as hardware tests."""
    for item in items:
        path = str(item.fspath)
        if "/test_hardware" in path or "hardware" in path.split("/tests/")[-1].split("/")[0]:
            item.add_marker(pytest.mark.hardware)
