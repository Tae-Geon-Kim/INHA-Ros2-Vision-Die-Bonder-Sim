from datetime import datetime, timedelta, timezone

from asyncpg import Connection
from fastapi import HTTPException, status

from web_backend.models.robot_log_models import (
    count_robot_error_logs,
    count_vision_align_logs,
    count_work_histories,
    insert_robot_error_log,
    insert_vision_align_log,
    insert_work_history,
    select_robot_error_logs,
    select_vision_align_logs,
    select_work_histories,
    select_work_history,
    update_work_history,
)
from web_backend.schemas.robot_log_schemas import (
    RobotErrorLogCreate,
    VisionAlignLogCreate,
    WorkHistoryCreate,
    WorkHistoryUpdate,
)


KST = timezone(timedelta(hours=9))


def _now_kst():
    return datetime.now(KST).replace(tzinfo=None)


def _to_db_timestamp(value: datetime | None):
    if value is None:
        return None

    if value.tzinfo is not None:
        return value.astimezone(KST).replace(tzinfo=None)

    return value


def _record_to_dict(record):
    return dict(record) if record is not None else None


def _records_to_list(records):
    return [dict(record) for record in records]


async def create_work_history_service(conn: Connection, data: WorkHistoryCreate):
    row = await insert_work_history(
        conn=conn,
        die_serial_number=data.die_serial_number,
        status=data.status,
        start_time=_to_db_timestamp(data.start_time) or _now_kst(),
    )

    return _record_to_dict(row)


async def update_work_history_service(
    conn: Connection,
    history_id: int,
    data: WorkHistoryUpdate,
):
    end_time = _to_db_timestamp(data.end_time)
    if end_time is None and data.status in {"DONE", "FAIL", "STOP"}:
        end_time = _now_kst()

    row = await update_work_history(
        conn=conn,
        history_id=history_id,
        status=data.status,
        end_time=end_time,
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 작업 이력입니다.",
        )

    return _record_to_dict(row)


async def list_work_histories_service(
    conn: Connection,
    limit: int,
    offset: int,
    status_filter: str | None = None,
    die_serial_number: str | None = None,
):
    rows = await select_work_histories(
        conn=conn,
        limit=limit,
        offset=offset,
        status=status_filter,
        die_serial_number=die_serial_number,
    )
    total = await count_work_histories(
        conn=conn,
        status=status_filter,
        die_serial_number=die_serial_number,
    )

    return {
        "items": _records_to_list(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def get_work_history_detail_service(conn: Connection, history_id: int):
    history = await select_work_history(conn, history_id)

    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 작업 이력입니다.",
        )

    error_logs = await select_robot_error_logs(
        conn=conn,
        history_id=history_id,
        limit=200,
        offset=0,
    )
    vision_align_logs = await select_vision_align_logs(
        conn=conn,
        history_id=history_id,
        limit=200,
        offset=0,
    )

    data = _record_to_dict(history)
    data["error_logs"] = _records_to_list(error_logs)
    data["vision_align_logs"] = _records_to_list(vision_align_logs)

    return data


async def create_robot_error_log_service(
    conn: Connection,
    data: RobotErrorLogCreate,
):
    if data.history_id is not None:
        await _ensure_work_history_exists(conn, data.history_id)

    row = await insert_robot_error_log(
        conn=conn,
        error_level=data.error_level,
        error_code=data.error_code,
        detail=data.detail,
        history_id=data.history_id,
        error_time=_to_db_timestamp(data.error_time) or _now_kst(),
    )

    return _record_to_dict(row)


async def list_robot_error_logs_service(
    conn: Connection,
    limit: int,
    offset: int,
    history_id: int | None = None,
    error_level: str | None = None,
):
    rows = await select_robot_error_logs(
        conn=conn,
        limit=limit,
        offset=offset,
        history_id=history_id,
        error_level=error_level,
    )
    total = await count_robot_error_logs(
        conn=conn,
        history_id=history_id,
        error_level=error_level,
    )

    return {
        "items": _records_to_list(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def create_vision_align_log_service(
    conn: Connection,
    data: VisionAlignLogCreate,
):
    await _ensure_work_history_exists(conn, data.history_id)

    row = await insert_vision_align_log(
        conn=conn,
        history_id=data.history_id,
        process_step=data.process_step,
        camera_type=data.camera_type,
        offset_x=data.offset_x,
        offset_y=data.offset_y,
        offset_theta=data.offset_theta,
        created_at=_to_db_timestamp(data.created_at) or _now_kst(),
    )

    return _record_to_dict(row)


async def list_vision_align_logs_service(
    conn: Connection,
    limit: int,
    offset: int,
    history_id: int | None = None,
    process_step: str | None = None,
    camera_type: str | None = None,
):
    rows = await select_vision_align_logs(
        conn=conn,
        limit=limit,
        offset=offset,
        history_id=history_id,
        process_step=process_step,
        camera_type=camera_type,
    )
    total = await count_vision_align_logs(
        conn=conn,
        history_id=history_id,
        process_step=process_step,
        camera_type=camera_type,
    )

    return {
        "items": _records_to_list(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def _ensure_work_history_exists(conn: Connection, history_id: int):
    history = await select_work_history(conn, history_id)

    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 작업 이력입니다.",
        )
