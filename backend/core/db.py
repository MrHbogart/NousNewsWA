from django.db import connection


def db_connect_params() -> dict:
    """psycopg.connect() kwargs for a dedicated connection to the default database.

    For session-scoped Postgres features Django's per-request connections can't
    hold: LISTEN (SSE streams) and the agent worker's advisory lock.
    """
    s = connection.settings_dict
    params = {"dbname": s["NAME"], "user": s["USER"], "password": s["PASSWORD"], "host": s["HOST"], "port": s["PORT"]}
    django_only = ("isolation_level", "server_side_binding", "assume_role", "pool")
    params.update({k: v for k, v in s.get("OPTIONS", {}).items() if k not in django_only})
    return {k: v for k, v in params.items() if v not in (None, "")}
