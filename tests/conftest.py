import os

import pytest


def pytest_configure(config) -> None:
    config.addinivalue_line('markers', 'integration: integration tests using Labelary')


def pytest_collection_modifyitems(config, items) -> None:
    if os.getenv('LABELARY_ENABLE', '0') == '1':
        return
    skip = pytest.mark.skip(reason='Set LABELARY_ENABLE=1 to run Labelary integration tests')
    for item in items:
        if 'integration' in item.keywords:
            item.add_marker(skip)
