import logging
import time
from collections.abc import Callable
from typing import Any

import psycopg
import pymysql
from django.conf import settings
from psycopg import sql

logger = logging.getLogger(__name__)

_POSTGRES_RETRYABLE_SQLSTATES = {"57P03", "53300"}
_MYSQL_RETRYABLE_ERROR_CODES = {2002, 2003, 2006, 2013}


def change_database_password(
    *,
    engine: str,
    host: str,
    port: int,
    dbname: str,
    username: str,
    old_password: str,
    new_password: str,
) -> None:
    if engine == "postgres":
        _change_postgres_password(
            host=host,
            port=port,
            dbname=dbname,
            username=username,
            old_password=old_password,
            new_password=new_password,
        )
        return

    if engine == "mysql":
        _change_mysql_password(
            host=host,
            port=port,
            username=username,
            old_password=old_password,
            new_password=new_password,
        )
        return

    raise ValueError(f"不支持的数据库类型: {engine}")


def verify_database_password(
    *,
    engine: str,
    host: str,
    port: int,
    dbname: str,
    username: str,
    password: str,
) -> bool:
    try:
        if engine == "postgres":
            connection = _connect_with_retry(
                lambda: psycopg.connect(
                    host=host,
                    port=port,
                    dbname=dbname or settings.POSTGRES_MAINTENANCE_DB,
                    user=username,
                    password=password,
                    connect_timeout=settings.DB_ROTATION_TIMEOUT,
                ),
                engine=engine,
            )
            connection.close()
            return True

        if engine == "mysql":
            connection = _connect_with_retry(
                lambda: pymysql.connect(
                    host=host,
                    port=port,
                    user=username,
                    password=password,
                    connect_timeout=settings.DB_ROTATION_TIMEOUT,
                    read_timeout=settings.DB_ROTATION_TIMEOUT,
                    write_timeout=settings.DB_ROTATION_TIMEOUT,
                    charset="utf8mb4",
                ),
                engine=engine,
            )
            connection.close()
            return True

    # 驱动异常类型较多，这里统一记录并返回验证失败。
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "目标数据库凭据验证失败：engine=%s host=%s port=%s error=%s",
            engine,
            host,
            port,
            exc,
        )
        return False

    return False


def _connect_with_retry(
    connect: Callable[[], Any],
    *,
    engine: str,
) -> Any:
    """建立数据库连接；仅对瞬态连接错误做有限次重试"""
    attempts = max(1, settings.DB_CONNECT_ATTEMPTS)

    for attempt in range(1, attempts + 1):
        try:
            return connect()
        except Exception as exc:
            if attempt >= attempts or not _is_retryable_connection_error(
                exc,
                engine,
            ):
                raise

            delay = max(
                0.0,
                settings.DB_CONNECT_BACKOFF_SECONDS,
            ) * (2 ** (attempt - 1))
            logger.warning(
                "连接目标数据库失败，%.2f 秒后重试（%s/%s）：engine=%s error=%s",
                delay,
                attempt,
                attempts,
                engine,
                exc,
            )
            time.sleep(delay)

    raise RuntimeError("数据库连接重试逻辑异常结束")


def _is_retryable_connection_error(exc: Exception, engine: str) -> bool:
    if engine == "postgres":
        if isinstance(exc, OSError):
            return True

        if not isinstance(exc, psycopg.OperationalError):
            return False

        sqlstate = _postgres_sqlstate(exc)
        if sqlstate is None:
            return True

        return sqlstate.startswith("08") or sqlstate in _POSTGRES_RETRYABLE_SQLSTATES

    if engine == "mysql":
        if isinstance(exc, OSError):
            return True

        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        return code in _MYSQL_RETRYABLE_ERROR_CODES

    return False


def _postgres_sqlstate(exc: Exception) -> str | None:
    return getattr(exc, "sqlstate", None) or getattr(exc.__cause__, "sqlstate", None)


def _change_postgres_password(
    *,
    host: str,
    port: int,
    dbname: str,
    username: str,
    old_password: str,
    new_password: str,
) -> None:
    database = dbname or settings.POSTGRES_MAINTENANCE_DB

    # 只重试建立连接；ALTER 一旦开始执行，失败交给轮换恢复流程判断。
    connection = _connect_with_retry(
        lambda: psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=username,
            password=old_password,
            connect_timeout=settings.DB_ROTATION_TIMEOUT,
        ),
        engine="postgres",
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(
                    sql.Identifier(username),
                ),
                [new_password],
            )
        connection.commit()
    except Exception:
        try:
            connection.rollback()
        except Exception:
            logger.debug("回滚目标数据库连接失败", exc_info=True)
        raise
    finally:
        connection.close()


def _change_mysql_password(
    *,
    host: str,
    port: int,
    username: str,
    old_password: str,
    new_password: str,
) -> None:
    # 只重试建立连接；ALTER 一旦开始执行，失败交给轮换恢复流程判断。
    connection = _connect_with_retry(
        lambda: pymysql.connect(
            host=host,
            port=port,
            user=username,
            password=old_password,
            connect_timeout=settings.DB_ROTATION_TIMEOUT,
            read_timeout=settings.DB_ROTATION_TIMEOUT,
            write_timeout=settings.DB_ROTATION_TIMEOUT,
            charset="utf8mb4",
            autocommit=True,
        ),
        engine="mysql",
    )

    try:
        with connection.cursor() as cursor:
            escaped_password = connection.escape(new_password)
            cursor.execute(f"ALTER USER USER() IDENTIFIED BY {escaped_password}")
    finally:
        connection.close()
