"""Pool de connexions asynchrones à PostgreSQL."""
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import DATABASE_URL

pool = AsyncConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row},
)