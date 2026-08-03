"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app import create_app
from config import Config
from extensions import db


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    GROQ_API_KEY = ""
    SECRET_KEY = "test-secret"


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app
