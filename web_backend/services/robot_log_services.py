import asyncio
import csv
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from asyncpg import Connection
from fastapi import HTTPException, status

from web_backend.models.robot_log_models import (
    append_place_completion,
    count_robot_error_logs,
    count_vision_align_logs,
    count_work_histories,
    delete_archived_robot_data,
    insert_robot_error_log,
    insert_vision_align_log,
    insert_work_history,
    select_archivable_robot_error_logs,
    select_archivable_vision_align_logs,
    select_archivable_work_histories,
    select_robot_error_logs,
    select_vision_align_logs,
    select_work_histories,
    select_work_history,
    try_acquire_robot_archive_lock,
    update_work_history,
)
from web_backend.schemas.robot_log_schemas import (
    PlaceCompletionCreate,
    RobotErrorLogCreate,
    VisionAlignLogCreate,
    WorkHistoryCreate,
    WorkHistoryUpdate,
)


KST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "data_archives"
ROBOT_ARCHIVE_LOCK_KEY = 724_2026_0712
ROBOT_DATA_RETENTION_DAYS = 7
ROBOT_ARCHIVE_BATCH_SIZE = 100

WORK_HISTORY_FIELDS = (
    "history_id",
    "die_serial_number",
    "stack_count",
    "place_completion_times",
    "start_time",
    "end_time",
    "status",
)
ROBOT_ERROR_FIELDS = (
    "log_id",
    "error_time",
    "error_level",
    "error_code",
    "detail",
    "history_id",
)
VISION_ALIGN_FIELDS = (
    "align_id",
    "history_id",
    "process_step",
    "camera_type",
    "offset_x",
    "offset_y",
    "offset_theta",
    "created_at",
)


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


def _csv_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (list, tuple)):
        return json.dumps([_csv_value(item) for item in value])
    return "" if value is None else value


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]):
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_robot_archive_bundle(
    archive_root: Path,
    archived_at: datetime,
    cutoff: datetime,
    work_rows: list[dict],
    error_rows: list[dict],
    align_rows: list[dict],
):
    parent = archive_root / archived_at.strftime("%Y") / archived_at.strftime("%m")
    parent.mkdir(parents=True, exist_ok=True)
    batch_name = (
        f"archive_{archived_at:%Y%m%dT%H%M%S}_{uuid4().hex[:8]}"
    )
    temporary_path = parent / f".{batch_name}.tmp"
    archive_path = parent / batch_name
    temporary_path.mkdir()

    try:
        _write_csv(
            temporary_path / "work_history.csv",
            WORK_HISTORY_FIELDS,
            work_rows,
        )
        _write_csv(
            temporary_path / "robot_error_logs.csv",
            ROBOT_ERROR_FIELDS,
            error_rows,
        )
        _write_csv(
            temporary_path / "vision_align_logs.csv",
            VISION_ALIGN_FIELDS,
            align_rows,
        )
        _write_csv(
            temporary_path / "archive_summary.csv",
            (
                "schema_version",
                "archived_at",
                "cutoff",
                "work_history_count",
                "robot_error_count",
                "vision_align_count",
            ),
            [
                {
                    "schema_version": 1,
                    "archived_at": archived_at,
                    "cutoff": cutoff,
                    "work_history_count": len(work_rows),
                    "robot_error_count": len(error_rows),
                    "vision_align_count": len(align_rows),
                }
            ],
        )
        _fsync_directory(temporary_path)
        os.replace(temporary_path, archive_path)
        _fsync_directory(parent)
    except Exception:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise

    return archive_path


async def create_work_history_service(conn: Connection, data: WorkHistoryCreate):
    row = await insert_work_history(
        conn=conn,
        die_serial_number=data.die_serial_number,
        stack_count=data.stack_count,
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


async def record_place_completion_service(
    conn: Connection,
    history_id: int,
    data: PlaceCompletionCreate,
):
    row = await append_place_completion(
        conn,
        history_id,
        data.chip_index,
        _to_db_timestamp(data.completed_at) or _now_kst(),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 작업 이력입니다.",
        )

    completion_count = len(row["place_completion_times"])
    if data.chip_index > row["stack_count"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="요청한 chip index가 작업의 적층 개수를 초과합니다.",
        )
    if completion_count < data.chip_index:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이전 chip의 place 비전 정렬 완료 기록이 먼저 필요합니다.",
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


async def archive_expired_robot_data(
    db_pool,
    archive_root: Path | str = DEFAULT_ARCHIVE_ROOT,
    retention_days: int = ROBOT_DATA_RETENTION_DAYS,
    now: datetime | None = None,
):
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    archived_at = _to_db_timestamp(now) or _now_kst()
    cutoff = archived_at - timedelta(days=retention_days)
    result = {
        "status": "empty",
        "archive_path": None,
        "cutoff": cutoff,
        "work_history": 0,
        "robot_error_logs": 0,
        "vision_align_logs": 0,
    }

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            lock_acquired = await try_acquire_robot_archive_lock(
                conn,
                ROBOT_ARCHIVE_LOCK_KEY,
            )
            if not lock_acquired:
                result["status"] = "locked"
                return result

            work_rows = _records_to_list(
                await select_archivable_work_histories(
                    conn,
                    cutoff,
                    ROBOT_ARCHIVE_BATCH_SIZE,
                )
            )
            history_ids = [row["history_id"] for row in work_rows]
            error_rows = _records_to_list(
                await select_archivable_robot_error_logs(
                    conn,
                    history_ids,
                    cutoff,
                )
            )
            align_rows = _records_to_list(
                await select_archivable_vision_align_logs(
                    conn,
                    history_ids,
                    cutoff,
                )
            )
            if not work_rows and not error_rows and not align_rows:
                return result

            archive_path = await asyncio.to_thread(
                _write_robot_archive_bundle,
                Path(archive_root),
                archived_at,
                cutoff,
                work_rows,
                error_rows,
                align_rows,
            )
            expected = {
                "work_history": len(work_rows),
                "robot_error_logs": len(error_rows),
                "vision_align_logs": len(align_rows),
            }
            deleted = await delete_archived_robot_data(
                conn,
                history_ids,
                [row["log_id"] for row in error_rows],
                [row["align_id"] for row in align_rows],
            )
            if deleted != expected:
                raise RuntimeError(
                    "CSV archive was written, but deleted row counts did not match "
                    f"the selected rows: expected={expected}, deleted={deleted}"
                )

            result.update(
                {
                    "status": "archived",
                    "archive_path": str(archive_path),
                    **expected,
                }
            )

    return result
