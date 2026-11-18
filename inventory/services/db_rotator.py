import pymysql
import psycopg
from django.conf import settings
from psycopg import sql


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
    if engine == 'postgres':
        _change_postgres_password(
            host=host,
            port=port,
            dbname=dbname,
            username=username,
            old_password=old_password,
            new_password=new_password,
        )
        return

    if engine == 'mysql':
        _change_mysql_password(
            host=host,
            port=port,
            username=username,
            old_password=old_password,
            new_password=new_password,
        )
        return

    raise ValueError(f'不支持的数据库类型: {engine}')


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
        if engine == 'postgres':
            with psycopg.connect(
                host=host,
                port=port,
                dbname=dbname or settings.POSTGRES_MAINTENANCE_DB,
                user=username,
                password=password,
                connect_timeout=settings.DB_ROTATION_TIMEOUT,
            ):
                return True

        if engine == 'mysql':
            connection = pymysql.connect(
                host=host,
                port=port,
                user=username,
                password=password,
                connect_timeout=settings.DB_ROTATION_TIMEOUT,
                read_timeout=settings.DB_ROTATION_TIMEOUT,
                write_timeout=settings.DB_ROTATION_TIMEOUT,
                charset='utf8mb4',
            )
            connection.close()
            return True

    except Exception:
        return False

    return False


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

    with psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=username,
        password=old_password,
        connect_timeout=settings.DB_ROTATION_TIMEOUT,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL('ALTER ROLE {} WITH PASSWORD %s').format(
                    sql.Identifier(username),
                ),
                [new_password],
            )


def _change_mysql_password(
    *,
    host: str,
    port: int,
    username: str,
    old_password: str,
    new_password: str,
) -> None:
    connection = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=old_password,
        connect_timeout=settings.DB_ROTATION_TIMEOUT,
        read_timeout=settings.DB_ROTATION_TIMEOUT,
        write_timeout=settings.DB_ROTATION_TIMEOUT,
        charset='utf8mb4',
        autocommit=True,
    )

    try:
        with connection.cursor() as cursor:
            escaped_password = connection.escape(new_password)
            cursor.execute(
                f'ALTER USER USER() IDENTIFIED BY {escaped_password}'
            )
    finally:
        connection.close()
