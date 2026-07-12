from asyncpg import Connection

# ========== 확인 / 검증 / 데이터 받아오기 ==========

# 특정 유저의 index를 통해서 해당 유저의 indx, id 값을 받아온다.
async def get_current_user_info(conn: Connection, user_index: int):

    sql = 'SELECT index, id FROM "user" WHERE index = $1'

    return await conn.fetchrow(sql, user_index)

# 사용자의 아이디로 해당 유저의 index, password 값을 가져온다.
async def get_info_by_id(conn: Connection, user_id: str):

    sql = 'SELECT index, password FROM "user" WHERE id = $1'

    return await conn.fetchrow(sql, user_id)