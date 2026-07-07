from datetime import datetime
from asyncpg import Connection

async def insert_user_log(
    conn: Connection,
    user_index: int,
    action_type: str,
    created_at: datetime
):

    sql = """
        INSERT INTO user_logs (user_index, action_type, created_at)
        VALUES($1, $2, $3)
    """

    return await conn.execute(sql, user_index, action_type, created_at)