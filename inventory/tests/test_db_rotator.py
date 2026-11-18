import psycopg
import pymysql
import pytest

from inventory.services.db_rotator import (
    _is_retryable_connection_error,
    change_database_password,
    verify_database_password,
)


class FakeCursor:
    def __init__(self, execute_error=None):
        self.executed = []
        self.execute_error = execute_error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params=None):
        if self.execute_error is not None:
            raise self.execute_error
        self.executed.append((statement, params))


class FakeConnection:
    def __init__(self, execute_error=None):
        self.cursor_instance = FakeCursor(execute_error)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def escape(self, value):
        return f"'{value}'"


def verify_postgres():
    return verify_database_password(
        engine='postgres',
        host='127.0.0.1',
        port=5432,
        dbname='appdb',
        username='app',
        password='secret',
    )


def verify_mysql():
    return verify_database_password(
        engine='mysql',
        host='127.0.0.1',
        port=3306,
        dbname='appdb',
        username='app',
        password='secret',
    )


def test_postgres_retryable_connection_errors():
    assert _is_retryable_connection_error(ConnectionRefusedError(), 'postgres')
    assert _is_retryable_connection_error(
        psycopg.errors.CannotConnectNow('starting'),
        'postgres',
    )
    assert _is_retryable_connection_error(
        psycopg.errors.TooManyConnections('full'),
        'postgres',
    )
    assert not _is_retryable_connection_error(
        psycopg.errors.InvalidPassword('bad password'),
        'postgres',
    )
    assert not _is_retryable_connection_error(
        psycopg.errors.InvalidCatalogName('missing database'),
        'postgres',
    )


def test_mysql_retryable_connection_errors():
    assert _is_retryable_connection_error(
        pymysql.err.OperationalError(2003, 'down'),
        'mysql',
    )
    assert _is_retryable_connection_error(
        pymysql.err.OperationalError(2013, 'lost connection'),
        'mysql',
    )
    assert not _is_retryable_connection_error(
        pymysql.err.OperationalError(1045, 'access denied'),
        'mysql',
    )
    assert not _is_retryable_connection_error(
        pymysql.err.OperationalError(1049, 'unknown database'),
        'mysql',
    )


def test_verify_postgres_retries_transient_failure(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    connection = FakeConnection()
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise psycopg.errors.CannotConnectNow('starting')
        return connection

    monkeypatch.setattr(
        'inventory.services.db_rotator.psycopg.connect',
        fake_connect,
    )

    assert verify_postgres() is True
    assert len(calls) == 3
    assert connection.closed is True


def test_verify_does_not_retry_authentication_failure(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        raise psycopg.errors.InvalidPassword('bad password')

    monkeypatch.setattr(
        'inventory.services.db_rotator.psycopg.connect',
        fake_connect,
    )

    assert verify_postgres() is False
    assert len(calls) == 1


def test_verify_stops_after_max_attempts(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        raise ConnectionRefusedError()

    monkeypatch.setattr(
        'inventory.services.db_rotator.psycopg.connect',
        fake_connect,
    )

    assert verify_postgres() is False
    assert len(calls) == 3


def test_verify_retry_uses_exponential_backoff(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0.5
    sleeps = []

    def fake_connect(**kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(
        'inventory.services.db_rotator.psycopg.connect',
        fake_connect,
    )
    monkeypatch.setattr(
        'inventory.services.db_rotator.time.sleep',
        sleeps.append,
    )

    assert verify_postgres() is False
    assert sleeps == [0.5, 1.0]


def test_verify_mysql_retries_transient_failure(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    connection = FakeConnection()
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise pymysql.err.OperationalError(2003, 'down')
        return connection

    monkeypatch.setattr(
        'inventory.services.db_rotator.pymysql.connect',
        fake_connect,
    )

    assert verify_mysql() is True
    assert len(calls) == 2
    assert connection.closed is True


def test_change_postgres_password_retries_connect(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    connection = FakeConnection()
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ConnectionRefusedError()
        return connection

    monkeypatch.setattr(
        'inventory.services.db_rotator.psycopg.connect',
        fake_connect,
    )

    change_database_password(
        engine='postgres',
        host='127.0.0.1',
        port=5432,
        dbname='appdb',
        username='app',
        old_password='old-password',
        new_password='new-password',
    )

    assert len(calls) == 2
    assert calls[-1]['password'] == 'old-password'
    assert connection.committed is True
    assert connection.closed is True
    assert connection.cursor_instance.executed[0][1] == ['new-password']


def test_change_postgres_password_does_not_retry_alter(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    connection = FakeConnection(execute_error=ConnectionRefusedError())
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        return connection

    monkeypatch.setattr(
        'inventory.services.db_rotator.psycopg.connect',
        fake_connect,
    )

    with pytest.raises(ConnectionRefusedError):
        change_database_password(
            engine='postgres',
            host='127.0.0.1',
            port=5432,
            dbname='appdb',
            username='app',
            old_password='old-password',
            new_password='new-password',
        )

    assert len(calls) == 1
    assert connection.rolled_back is True
    assert connection.closed is True


def test_change_mysql_password_retries_connect(monkeypatch, settings):
    settings.DB_CONNECT_ATTEMPTS = 3
    settings.DB_CONNECT_BACKOFF_SECONDS = 0
    connection = FakeConnection()
    calls = []

    def fake_connect(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise pymysql.err.OperationalError(2003, 'down')
        return connection

    monkeypatch.setattr(
        'inventory.services.db_rotator.pymysql.connect',
        fake_connect,
    )

    change_database_password(
        engine='mysql',
        host='127.0.0.1',
        port=3306,
        dbname='appdb',
        username='app',
        old_password='old-password',
        new_password='new-password',
    )

    assert len(calls) == 2
    assert connection.closed is True
    statement, _ = connection.cursor_instance.executed[0]
    assert statement == "ALTER USER USER() IDENTIFIED BY 'new-password'"
