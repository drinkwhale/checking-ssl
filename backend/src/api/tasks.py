"""
작업 관리 API 엔드포인트

스케줄러 및 백그라운드 작업 관리 API를 제공합니다.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..scheduler import get_scheduler
from ..background import (
    get_background_executor,
    submit_ssl_check,
    submit_notification_task,
    TaskStatus,
    TaskPriority
)


# APIRouter 생성
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# Request/Response 모델 정의
class SchedulerStatusResponse(BaseModel):
    """스케줄러 상태 응답"""
    scheduler_running: bool = Field(..., description="스케줄러 실행 상태")
    jobs: List[Dict[str, Any]] = Field(..., description="등록된 작업 목록")
    total_jobs: int = Field(..., description="총 작업 수")


class TriggerJobRequest(BaseModel):
    """작업 수동 실행 요청"""
    job_id: str = Field(..., description="실행할 작업 ID")


class SubmitSSLCheckRequest(BaseModel):
    """SSL 체크 작업 제출 요청"""
    website_ids: Optional[List[str]] = Field(None, description="체크할 웹사이트 ID 목록")
    priority: str = Field("normal", description="작업 우선순위 (low, normal, high, critical)")


class SubmitNotificationRequest(BaseModel):
    """알림 작업 제출 요청"""
    notification_days: Optional[List[int]] = Field([30, 14, 7, 3, 1], description="알림 발송 일수 목록")
    priority: str = Field("high", description="작업 우선순위 (low, normal, high, critical)")


class TaskSubmissionResponse(BaseModel):
    """작업 제출 응답"""
    task_id: str = Field(..., description="작업 ID")
    status: str = Field(..., description="작업 상태")
    message: str = Field(..., description="응답 메시지")


class BackgroundTaskResponse(BaseModel):
    """백그라운드 작업 응답"""
    task_id: str = Field(..., description="작업 ID")
    name: Optional[str] = Field(None, description="작업 이름")
    status: str = Field(..., description="작업 상태")
    priority: Optional[int] = Field(None, description="작업 우선순위")
    max_retries: Optional[int] = Field(None, description="최대 재시도 횟수")
    retry_count: int = Field(0, description="현재 재시도 횟수")
    result: Optional[Dict[str, Any]] = Field(None, description="작업 결과")
    error: Optional[str] = Field(None, description="오류 메시지")
    start_time: Optional[datetime] = Field(None, description="시작 시간")
    end_time: Optional[datetime] = Field(None, description="종료 시간")
    duration_seconds: Optional[float] = Field(None, description="실행 소요 시간")
    created_at: Optional[datetime] = Field(None, description="생성 시간")
    scheduled_at: Optional[datetime] = Field(None, description="예약 실행 시간")


class ExecutorStatsResponse(BaseModel):
    """실행기 통계 응답"""
    is_running: bool = Field(..., description="실행기 실행 상태")
    total_tasks: int = Field(..., description="총 작업 수")
    pending_tasks: int = Field(..., description="대기 중인 작업 수")
    running_tasks: int = Field(..., description="실행 중인 작업 수")
    max_concurrent_tasks: int = Field(..., description="최대 동시 실행 작업 수")
    status_distribution: Dict[str, int] = Field(..., description="상태별 분포")
    semaphore_available: int = Field(..., description="사용 가능한 세마포어 수")
    last_cleanup: Optional[str] = Field(None, description="마지막 정리 시간")


# 스케줄러 관리 엔드포인트

@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status() -> SchedulerStatusResponse:
    """
    스케줄러 상태 조회

    현재 스케줄러의 실행 상태와 등록된 작업 목록을 조회합니다.
    """
    try:
        scheduler = get_scheduler()
        status = scheduler.get_job_status()

        return SchedulerStatusResponse(**status)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"스케줄러 상태 조회 실패: {str(e)}"
        )


@router.post("/scheduler/trigger", response_model=Dict[str, Any])
async def trigger_scheduled_job(request: TriggerJobRequest) -> Dict[str, Any]:
    """
    스케줄된 작업 수동 실행

    등록된 스케줄 작업을 즉시 실행합니다.
    """
    try:
        scheduler = get_scheduler()
        result = await scheduler.trigger_job_now(request.job_id)

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"작업 실행 실패: {str(e)}"
        )


# 백그라운드 작업 관리 엔드포인트

@router.post("/background/ssl-check", response_model=TaskSubmissionResponse)
async def submit_ssl_check_task(request: SubmitSSLCheckRequest) -> TaskSubmissionResponse:
    """
    SSL 체크 작업 제출

    백그라운드에서 SSL 인증서 체크 작업을 실행합니다.
    """
    try:
        # 우선순위 변환
        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL
        }

        priority = priority_map.get(request.priority.lower(), TaskPriority.NORMAL)

        # 작업 제출
        task_id = submit_ssl_check(
            website_ids=request.website_ids,
            priority=priority
        )

        return TaskSubmissionResponse(
            task_id=task_id,
            status="submitted",
            message="SSL 체크 작업이 성공적으로 제출되었습니다"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SSL 체크 작업 제출 실패: {str(e)}"
        )


@router.post("/background/notifications", response_model=TaskSubmissionResponse)
async def submit_notification_task_endpoint(request: SubmitNotificationRequest) -> TaskSubmissionResponse:
    """
    알림 작업 제출

    백그라운드에서 만료 알림 작업을 실행합니다.
    """
    try:
        # 우선순위 변환
        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL
        }

        priority = priority_map.get(request.priority.lower(), TaskPriority.HIGH)

        # 작업 제출
        task_id = submit_notification_task(
            notification_days=request.notification_days,
            priority=priority
        )

        return TaskSubmissionResponse(
            task_id=task_id,
            status="submitted",
            message="알림 작업이 성공적으로 제출되었습니다"
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"알림 작업 제출 실패: {str(e)}"
        )


@router.get("/background/tasks", response_model=List[BackgroundTaskResponse])
async def list_background_tasks(
    task_status: Optional[str] = Query(None, description="작업 상태 필터"),
    limit: int = Query(50, ge=1, le=500, description="결과 수 제한")
) -> List[BackgroundTaskResponse]:
    """
    백그라운드 작업 목록 조회

    제출된 백그라운드 작업들의 상태를 조회합니다.
    """
    try:
        executor = get_background_executor()

        # 상태 필터 변환
        status_filter = None
        if task_status:
            try:
                status_filter = TaskStatus(task_status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"유효하지 않은 작업 상태: {task_status}"
                )

        # 작업 목록 조회
        tasks = executor.list_tasks(status=status_filter, limit=limit)

        # 응답 변환
        response_tasks = []
        for task in tasks:
            response_tasks.append(BackgroundTaskResponse(
                task_id=task["task_id"],
                name=task.get("name"),
                status=task["status"],
                priority=task.get("priority"),
                max_retries=task.get("max_retries"),
                retry_count=task["retry_count"],
                result=task["result"],
                error=task["error"],
                start_time=datetime.fromisoformat(task["start_time"]) if task["start_time"] else None,
                end_time=datetime.fromisoformat(task["end_time"]) if task["end_time"] else None,
                duration_seconds=task["duration_seconds"],
                created_at=datetime.fromisoformat(task["created_at"]) if task.get("created_at") else None,
                scheduled_at=datetime.fromisoformat(task["scheduled_at"]) if task.get("scheduled_at") else None
            ))

        return response_tasks

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"백그라운드 작업 목록 조회 실패: {str(e)}"
        )


@router.get("/background/tasks/{task_id}", response_model=BackgroundTaskResponse)
async def get_background_task(task_id: str) -> BackgroundTaskResponse:
    """
    특정 백그라운드 작업 조회

    작업 ID로 특정 백그라운드 작업의 상세 정보를 조회합니다.
    """
    try:
        executor = get_background_executor()
        result = executor.get_task_result(task_id)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="작업을 찾을 수 없습니다"
            )

        # 작업 목록에서 추가 정보 조회
        tasks = executor.list_tasks(limit=1000)  # 충분히 큰 수로 조회
        task_info = None

        for task in tasks:
            if task["task_id"] == task_id:
                task_info = task
                break

        if not task_info:
            # 결과만 있는 경우
            task_info = result.to_dict()

        return BackgroundTaskResponse(
            task_id=task_info["task_id"],
            name=task_info.get("name"),
            status=task_info["status"],
            priority=task_info.get("priority"),
            max_retries=task_info.get("max_retries"),
            retry_count=task_info["retry_count"],
            result=task_info["result"],
            error=task_info["error"],
            start_time=datetime.fromisoformat(task_info["start_time"]) if task_info["start_time"] else None,
            end_time=datetime.fromisoformat(task_info["end_time"]) if task_info["end_time"] else None,
            duration_seconds=task_info["duration_seconds"],
            created_at=datetime.fromisoformat(task_info["created_at"]) if task_info.get("created_at") else None,
            scheduled_at=datetime.fromisoformat(task_info["scheduled_at"]) if task_info.get("scheduled_at") else None
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"백그라운드 작업 조회 실패: {str(e)}"
        )


@router.get("/background/stats", response_model=ExecutorStatsResponse)
async def get_executor_stats() -> ExecutorStatsResponse:
    """
    백그라운드 실행기 통계 조회

    백그라운드 작업 실행기의 현재 상태와 통계를 조회합니다.
    """
    try:
        executor = get_background_executor()
        stats = executor.get_executor_stats()

        return ExecutorStatsResponse(**stats)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"실행기 통계 조회 실패: {str(e)}"
        )