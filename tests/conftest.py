"""Pytest fixtures for lilith-whatsapp tests."""

import pathlib

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Load .env from project root so DATABASE_URL is set for integration tests."""
    try:
        from dotenv import load_dotenv

        root = pathlib.Path(__file__).resolve().parent.parent
        load_dotenv(root / ".env")
    except ImportError:
        pass
