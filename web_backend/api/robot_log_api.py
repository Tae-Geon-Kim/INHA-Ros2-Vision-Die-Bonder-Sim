from fastapi import APIRouter, Depends, Query, status
from asyncpg import Connection

from web_backend.db.postgres_connection import get_db
from web_backend.schemas.common_schemas import CommonResponse
from web_backend.schemas.robot_log_schemas import (
    ErrorLevel,
    ProcessStep,
    RobotErrorLogCreate,
    VisionAlignLogCreate,
    WorkHistoryCreate,
    WorkHistoryUpdate,
    WorkStatus,
)
from web_backend.services.robot_log_services import (
    create_robot_error_log_service,
    create_vision_align_log_service,
    create_work_history_service,
    get_work_history_detail_service,
    list_robot_error_logs_service,
    list_vision_align_logs_service,
    list_work_histories_service,
    update_work_history_service,
)


router = APIRouter()


@router.post(
    "/work-history",
    response_model=CommonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[로봇 로그] 작업 이력 생성",
    description="다이 본딩 작업 시작 시 die serial number와 시작 상태를 저장합니다.",
)
async def create_work_history(
    data: WorkHistoryCreate,
    conn: Connection = Depends(get_db),
):
    result = await create_work_history_service(conn, data)

    return CommonResponse(message="작업 이력이 생성되었습니다.", data=result)


@router.patch(
    "/work-history/{history_id}",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 로그] 작업 이력 수정",
    description="작업 종료 시간 또는 상태를 갱신합니다.",
)
async def patch_work_history(
    history_id: int,
    data: WorkHistoryUpdate,
    conn: Connection = Depends(get_db),
):
    result = await update_work_history_service(conn, history_id, data)

    return CommonResponse(message="작업 이력이 수정되었습니다.", data=result)


@router.get(
    "/work-history",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 로그] 작업 이력 목록 조회",
    description="웹 화면에서 작업 이력 목록을 최신순으로 조회합니다.",
)
async def get_work_histories(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: WorkStatus | None = Query(default=None, alias="status"),
    die_serial_number: str | None = Query(default=None),
    conn: Connection = Depends(get_db),
):
    result = await list_work_histories_service(
        conn=conn,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
        die_serial_number=die_serial_number,
    )

    return CommonResponse(data=result)


@router.get(
    "/work-history/{history_id}",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 로그] 작업 이력 상세 조회",
    description="작업 이력과 연결된 에러 로그, 비전 정렬 로그를 함께 조회합니다.",
)
async def get_work_history_detail(
    history_id: int,
    conn: Connection = Depends(get_db),
):
    result = await get_work_history_detail_service(conn, history_id)

    return CommonResponse(data=result)


@router.post(
    "/errors",
    response_model=CommonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[로봇 로그] 에러 로그 생성",
    description="로봇 제어 중 발생한 경고 또는 에러를 저장합니다.",
)
async def create_robot_error_log(
    data: RobotErrorLogCreate,
    conn: Connection = Depends(get_db),
):
    result = await create_robot_error_log_service(conn, data)

    return CommonResponse(message="로봇 에러 로그가 저장되었습니다.", data=result)


@router.get(
    "/errors",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 로그] 에러 로그 목록 조회",
    description="웹 화면에서 로봇 에러 로그를 최신순으로 조회합니다.",
)
async def get_robot_error_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    history_id: int | None = Query(default=None, ge=1),
    error_level: ErrorLevel | None = Query(default=None),
    conn: Connection = Depends(get_db),
):
    result = await list_robot_error_logs_service(
        conn=conn,
        limit=limit,
        offset=offset,
        history_id=history_id,
        error_level=error_level,
    )

    return CommonResponse(data=result)


@router.post(
    "/vision-align",
    response_model=CommonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[로봇 로그] 비전 정렬 로그 생성",
    description="PICK/PLACE 단계의 카메라 보정 offset 값을 저장합니다.",
)
async def create_vision_align_log(
    data: VisionAlignLogCreate | list[VisionAlignLogCreate],
    conn: Connection = Depends(get_db),
):
    is_batch = isinstance(data, list)
    entries = data if is_batch else [data]
    result = [
        await create_vision_align_log_service(conn, entry)
        for entry in entries
    ]

    return CommonResponse(
        message=f"비전 정렬 로그 {len(result)}건이 저장되었습니다.",
        data=result if is_batch else result[0],
    )


@router.get(
    "/vision-align",
    response_model=CommonResponse,
    status_code=status.HTTP_200_OK,
    summary="[로봇 로그] 비전 정렬 로그 목록 조회",
    description="웹 화면에서 비전 정렬 로그를 최신순으로 조회합니다.",
)
async def get_vision_align_logs(
    limit: int = Query(default=50, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    history_id: int | None = Query(default=None, ge=1),
    process_step: ProcessStep | None = Query(default=None),
    camera_type: str | None = Query(default=None),
    conn: Connection = Depends(get_db),
):
    result = await list_vision_align_logs_service(
        conn=conn,
        limit=limit,
        offset=offset,
        history_id=history_id,
        process_step=process_step,
        camera_type=camera_type,
    )

    return CommonResponse(data=result)
