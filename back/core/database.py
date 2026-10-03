import psycopg2

from core.config import PG_CONNECTION_STRING


def get_db():
    conn=psycopg2.connect(PG_CONNECTION_STRING)
    try:
        yield conn
    finally:
        conn.close()
