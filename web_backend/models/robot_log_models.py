from datetime import datetime

from asyncpg import Connection


async def insert_work_history(
    conn: Connection,
    die_serial_number: str,
    stack_count: int,
    status: str,
    start_time: datetime,
):
    sql = """
        INSERT INTO work_history (
            die_serial_number, stack_count, status, start_time
        )
        VALUES ($1, $2, $3, $4)
        RETURNING
            history_id, die_serial_number, stack_count, place_completion_times,
            start_time, end_time, status
    """

    return await conn.fetchrow(
        sql,
        die_serial_number,
        stack_count,
        status,
        start_time,
    )


async def update_work_history(
    conn: Connection,
    history_id: int,
    status: str | None,
    end_time: datetime | None,
):
    sql = """
        UPDATE work_history
        SET
            status = COALESCE($2, status),
            end_time = COALESCE($3, end_time)
        WHERE history_id = $1
        RETURNING
            history_id, die_serial_number, stack_count, place_completion_times,
            start_time, end_time, status
    """

    return await conn.fetchrow(sql, history_id, status, end_time)


async def select_work_history(conn: Connection, history_id: int):
    sql = """
        SELECT
            history_id, die_serial_number, stack_count, place_completion_times,
            start_time, end_time, status
        FROM work_history
        WHERE history_id = $1
    """

    return await conn.fetchrow(sql, history_id)


async def select_work_histories(
    conn: Connection,
    limit: int,
    offset: int,
    status: str | None = None,
    die_serial_number: str | None = None,
):
    sql = """
        SELECT
            history_id, die_serial_number, stack_count, place_completion_times,
            start_time, end_time, status
        FROM work_history
        WHERE ($1::varchar IS NULL OR status = $1)
          AND ($2::varchar IS NULL OR die_serial_number ILIKE '%' || $2 || '%')
        ORDER BY start_time DESC, history_id DESC
        LIMIT $3 OFFSET $4
    """

    return await conn.fetch(sql, status, die_serial_number, limit, offset)


async def count_work_histories(
    conn: Connection,
    status: str | None = None,
    die_serial_number: str | None = None,
):
    sql = """
        SELECT COUNT(*) AS total
        FROM work_history
        WHERE ($1::varchar IS NULL OR status = $1)
          AND ($2::varchar IS NULL OR die_serial_number ILIKE '%' || $2 || '%')
    """

    return await conn.fetchval(sql, status, die_serial_number)


async def append_place_completion(
    conn: Connection,
    history_id: int,
    chip_index: int,
    completed_at: datetime,
):
    sql = """
        UPDATE work_history
        SET place_completion_times = CASE
            WHEN $2 <= stack_count
             AND cardinality(place_completion_times) = $2 - 1
            THEN array_append(place_completion_times, $3)
            ELSE place_completion_times
        END
        WHERE history_id = $1
        RETURNING
            history_id, die_serial_number, stack_count, place_completion_times,
            start_time, end_time, status
    """

    return await conn.fetchrow(sql, history_id, chip_index, completed_at)


async def insert_robot_error_log(
    conn: Connection,
    error_level: str,
    error_code: str | None,
    detail: str | None,
    history_id: int | None,
    error_time: datetime,
):
    sql = """
        INSERT INTO robot_error_logs (
            error_level, error_code, detail, history_id, error_time
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING log_id, error_time, error_level, error_code, detail, history_id
    """

    return await conn.fetchrow(
        sql, error_level, error_code, detail, history_id, error_time
    )


async def select_robot_error_logs(
    conn: Connection,
    limit: int,
    offset: int,
    history_id: int | None = None,
    error_level: str | None = None,
):
    sql = """
        SELECT log_id, error_time, error_level, error_code, detail, history_id
        FROM robot_error_logs
        WHERE ($1::int IS NULL OR history_id = $1)
          AND ($2::varchar IS NULL OR error_level = $2)
        ORDER BY error_time DESC, log_id DESC
        LIMIT $3 OFFSET $4
    """

    return await conn.fetch(sql, history_id, error_level, limit, offset)


async def count_robot_error_logs(
    conn: Connection,
    history_id: int | None = None,
    error_level: str | None = None,
):
    sql = """
        SELECT COUNT(*) AS total
        FROM robot_error_logs
        WHERE ($1::int IS NULL OR history_id = $1)
          AND ($2::varchar IS NULL OR error_level = $2)
    """

    return await conn.fetchval(sql, history_id, error_level)


async def insert_vision_align_log(
    conn: Connection,
    history_id: int,
    process_step: str,
    camera_type: str,
    offset_x: float,
    offset_y: float,
    offset_theta: float,
    created_at: datetime,
):
    sql = """
        INSERT INTO vision_align_logs (
            history_id, process_step, camera_type,
            offset_x, offset_y, offset_theta, created_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING
            align_id, history_id, process_step, camera_type,
            offset_x, offset_y, offset_theta, created_at
    """

    return await conn.fetchrow(
        sql,
        history_id,
        process_step,
        camera_type,
        offset_x,
        offset_y,
        offset_theta,
        created_at,
    )


async def select_vision_align_logs(
    conn: Connection,
    limit: int,
    offset: int,
    history_id: int | None = None,
    process_step: str | None = None,
    camera_type: str | None = None,
):
    sql = """
        SELECT
            align_id, history_id, process_step, camera_type,
            offset_x, offset_y, offset_theta, created_at
        FROM vision_align_logs
        WHERE ($1::int IS NULL OR history_id = $1)
          AND ($2::varchar IS NULL OR process_step = $2)
          AND ($3::varchar IS NULL OR camera_type = $3)
        ORDER BY created_at DESC, align_id DESC
        LIMIT $4 OFFSET $5
    """

    return await conn.fetch(
        sql, history_id, process_step, camera_type, limit, offset
    )


async def count_vision_align_logs(
    conn: Connection,
    history_id: int | None = None,
    process_step: str | None = None,
    camera_type: str | None = None,
):
    sql = """
        SELECT COUNT(*) AS total
        FROM vision_align_logs
        WHERE ($1::int IS NULL OR history_id = $1)
          AND ($2::varchar IS NULL OR process_step = $2)
          AND ($3::varchar IS NULL OR camera_type = $3)
    """

    return await conn.fetchval(sql, history_id, process_step, camera_type)


async def try_acquire_robot_archive_lock(
    conn: Connection,
    lock_key: int,
):
    sql = "SELECT pg_try_advisory_xact_lock($1)"
    return bool(await conn.fetchval(sql, lock_key))


async def select_archivable_work_histories(
    conn: Connection,
    cutoff: datetime,
    limit: int,
):
    sql = """
        SELECT
            history_id, die_serial_number, stack_count, place_completion_times,
            start_time, end_time, status
        FROM work_history
        WHERE status IN ('DONE', 'FAIL', 'STOP')
          AND COALESCE(end_time, start_time) < $1
        ORDER BY history_id
        LIMIT $2
        FOR UPDATE SKIP LOCKED
    """

    return await conn.fetch(sql, cutoff, limit)


async def select_archivable_robot_error_logs(
    conn: Connection,
    history_ids: list[int],
    cutoff: datetime,
):
    sql = """
        SELECT log_id, error_time, error_level, error_code, detail, history_id
        FROM robot_error_logs
        WHERE history_id = ANY($1::int[])
           OR (history_id IS NULL AND error_time < $2)
        ORDER BY log_id
        FOR UPDATE
    """

    return await conn.fetch(sql, history_ids, cutoff)


async def select_archivable_vision_align_logs(
    conn: Connection,
    history_ids: list[int],
    cutoff: datetime,
):
    sql = """
        SELECT
            align_id, history_id, process_step, camera_type,
            offset_x, offset_y, offset_theta, created_at
        FROM vision_align_logs
        WHERE history_id = ANY($1::int[])
           OR (history_id IS NULL AND created_at < $2)
        ORDER BY align_id
        FOR UPDATE
    """

    return await conn.fetch(sql, history_ids, cutoff)


async def delete_archived_robot_data(
    conn: Connection,
    history_ids: list[int],
    error_log_ids: list[int],
    align_log_ids: list[int],
):
    deleted = {
        "work_history": 0,
        "robot_error_logs": 0,
        "vision_align_logs": 0,
    }

    if align_log_ids:
        deleted["vision_align_logs"] = await conn.fetchval(
            """
            WITH deleted_rows AS (
                DELETE FROM vision_align_logs
                WHERE align_id = ANY($1::int[])
                RETURNING 1
            )
            SELECT COUNT(*) FROM deleted_rows
            """,
            align_log_ids,
        )
    if error_log_ids:
        deleted["robot_error_logs"] = await conn.fetchval(
            """
            WITH deleted_rows AS (
                DELETE FROM robot_error_logs
                WHERE log_id = ANY($1::int[])
                RETURNING 1
            )
            SELECT COUNT(*) FROM deleted_rows
            """,
            error_log_ids,
        )
    if history_ids:
        deleted["work_history"] = await conn.fetchval(
            """
            WITH deleted_rows AS (
                DELETE FROM work_history
                WHERE history_id = ANY($1::int[])
                RETURNING 1
            )
            SELECT COUNT(*) FROM deleted_rows
            """,
            history_ids,
        )

    return deleted
