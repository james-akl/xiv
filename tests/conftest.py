"""Pytest configuration"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="run integration tests")

@pytest.fixture
def integration_mode(request):
    return request.config.getoption("--integration")

@pytest.fixture
def fixtures_dir():
    return os.path.join(os.path.dirname(__file__), 'fixtures')
