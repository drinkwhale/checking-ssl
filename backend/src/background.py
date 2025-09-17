"""
백그라운드 작업 실행기

비동기 작업 실행, 오류 처리, 재시도 로직을 담당하는 백그라운드 작업 관리자입니다.
"""

import asyncio
import functools
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union, Coroutine
from dataclasses import dataclass, field

from .database import get_async_session
from .services.ssl_service import SSLService
from .services.notification_service import NotificationService
from .services.website_service import WebsiteService


# 로깅 설정
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """작업 상태"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskPriority(Enum):
    """작업 우선순위"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class TaskResult:
    """작업 결과"""
    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "retry_count": self.retry_count,
            "metadata": self.metadata
        }


@dataclass
class BackgroundTask:
    """백그라운드 작업"""
    task_id: str
    name: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 3
    retry_delay: float = 5.0  # 초
    timeout: Optional[float] = None  # 초
    created_at: datetime = field(default_factory=datetime.utcnow)
    scheduled_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BackgroundTaskExecutor:
    """백그라운드 작업 실행기"""

    def __init__(
        self,
        max_concurrent_tasks: int = 5,
        default_timeout: float = 300.0,  # 5분
        cleanup_interval: float = 3600.0,  # 1시간
        max_result_age: float = 86400.0,  # 24시간
    ):
        """
        Args:
            max_concurrent_tasks: 최대 동시 실행 작업 수
            default_timeout: 기본 타임아웃 (초)
            cleanup_interval: 결과 정리 간격 (초)
            max_result_age: 결과 보관 기간 (초)
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.default_timeout = default_timeout
        self.cleanup_interval = cleanup_interval
        self.max_result_age = max_result_age

        # 작업 관리
        self._tasks: Dict[str, BackgroundTask] = {}
        self._results: Dict[str, TaskResult] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

        # 실행기 상태
        self._is_running = False
        self._executor_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """백그라운드 작업 실행기 시작"""
        if self._is_running:
            logger.warning("백그라운드 작업 실행기가 이미 실행 중입니다")
            return

        logger.info("백그라운드 작업 실행기 시작")
        self._is_running = True

        # 메인 실행 루프 시작
        self._executor_task = asyncio.create_task(self._execution_loop())

        # 정리 작업 시작
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """백그라운드 작업 실행기 종료"""
        if not self._is_running:
            logger.warning("백그라운드 작업 실행기가 실행 중이 아닙니다")
            return

        logger.info("백그라운드 작업 실행기 종료 중...")
        self._is_running = False

        # 실행 중인 작업들 취소
        for task_id, task in self._running_tasks.items():
            logger.info(f"실행 중인 작업 취소: {task_id}")
            task.cancel()

            # 결과 업데이트
            if task_id in self._results:
                self._results[task_id].status = TaskStatus.CANCELLED
                self._results[task_id].end_time = datetime.utcnow()

        # 대기 중인 작업들 취소
        for task_id, background_task in self._tasks.items():
            logger.info(f"대기 중인 작업 취소: {task_id}")
            if task_id not in self._results:
                self._results[task_id] = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.CANCELLED
                )

        # 실행기 태스크들 정리
        if self._executor_task and not self._executor_task.done():
            self._executor_task.cancel()
            try:
                await self._executor_task
            except asyncio.CancelledError:
                pass

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # 남은 실행 중인 작업들 대기
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)

        self._tasks.clear()
        self._running_tasks.clear()

        logger.info("백그라운드 작업 실행기 종료 완료")

    def submit_task(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args,
        name: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        timeout: Optional[float] = None,
        scheduled_at: Optional[datetime] = None,
        **kwargs
    ) -> str:
        """작업 제출

        Args:
            func: 실행할 비동기 함수
            *args: 함수 인자
            name: 작업 이름
            priority: 우선순위
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 지연 시간 (초)
            timeout: 타임아웃 (초)
            scheduled_at: 예약 실행 시간
            **kwargs: 함수 키워드 인자

        Returns:
            작업 ID
        """
        task_id = str(uuid.uuid4())
        task_name = name or f"{func.__name__}_{task_id[:8]}"

        task = BackgroundTask(
            task_id=task_id,
            name=task_name,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            max_retries=max_retries,
            retry_delay=retry_delay,
            timeout=timeout or self.default_timeout,
            scheduled_at=scheduled_at,
            metadata={"submitted_at": datetime.utcnow().isoformat()}
        )

        self._tasks[task_id] = task
        self._results[task_id] = TaskResult(
            task_id=task_id,
            status=TaskStatus.PENDING
        )

        logger.info(f"작업 제출: {task_name} ({task_id})")
        return task_id

    def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """작업 결과 조회"""
        return self._results.get(task_id)

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """작업 상태 조회"""
        result = self._results.get(task_id)
        return result.status if result else None

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """작업 목록 조회"""
        tasks = []

        for task_id, result in self._results.items():
            if status and result.status != status:
                continue

            task_info = result.to_dict()

            # 작업 정보 추가
            if task_id in self._tasks:
                background_task = self._tasks[task_id]
                task_info.update({
                    "name": background_task.name,
                    "priority": background_task.priority.value,
                    "max_retries": background_task.max_retries,
                    "created_at": background_task.created_at.isoformat(),
                    "scheduled_at": background_task.scheduled_at.isoformat() if background_task.scheduled_at else None
                })

            tasks.append(task_info)

        # 생성 시간 역순 정렬
        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        if limit:
            tasks = tasks[:limit]

        return tasks

    def get_executor_stats(self) -> Dict[str, Any]:
        """실행기 통계 조회"""
        status_counts = {}
        for result in self._results.values():
            status = result.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "is_running": self._is_running,
            "total_tasks": len(self._results),
            "pending_tasks": len(self._tasks),
            "running_tasks": len(self._running_tasks),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "status_distribution": status_counts,
            "semaphore_available": self._semaphore._value,
            "last_cleanup": getattr(self, '_last_cleanup', None)
        }

    async def _execution_loop(self) -> None:
        """메인 실행 루프"""
        logger.info("백그라운드 작업 실행 루프 시작")

        try:
            while self._is_running:
                await self._process_pending_tasks()
                await asyncio.sleep(1)  # 1초마다 체크

        except asyncio.CancelledError:
            logger.info("백그라운드 작업 실행 루프 취소됨")
        except Exception as e:
            logger.error(f"백그라운드 작업 실행 루프 오류: {e}")
        finally:
            logger.info("백그라운드 작업 실행 루프 종료")

    async def _process_pending_tasks(self) -> None:
        """대기 중인 작업들 처리"""
        if not self._tasks:
            return

        # 실행 가능한 작업들 필터링
        now = datetime.utcnow()
        ready_tasks = []

        for task_id, task in list(self._tasks.items()):
            # 스케줄된 시간 확인
            if task.scheduled_at and task.scheduled_at > now:
                continue

            # 이미 실행 중인지 확인
            if task_id in self._running_tasks:
                continue

            ready_tasks.append((task_id, task))

        if not ready_tasks:
            return

        # 우선순위별로 정렬
        ready_tasks.sort(key=lambda x: x[1].priority.value, reverse=True)

        # 동시 실행 제한 확인 후 작업 시작
        for task_id, task in ready_tasks:
            if len(self._running_tasks) >= self.max_concurrent_tasks:
                break

            await self._start_task(task_id, task)

    async def _start_task(self, task_id: str, background_task: BackgroundTask) -> None:
        """작업 시작"""
        logger.info(f"작업 시작: {background_task.name} ({task_id})")

        # 결과 상태 업데이트
        result = self._results[task_id]
        result.status = TaskStatus.RUNNING
        result.start_time = datetime.utcnow()

        # 작업 실행
        async def run_with_semaphore():
            async with self._semaphore:
                return await self._execute_task(task_id, background_task)

        task = asyncio.create_task(run_with_semaphore())
        self._running_tasks[task_id] = task

        # 작업이 완료되면 정리
        task.add_done_callback(
            functools.partial(self._task_completed, task_id)
        )

    async def _execute_task(
        self,
        task_id: str,
        background_task: BackgroundTask
    ) -> Any:
        """작업 실행"""
        result = self._results[task_id]

        try:
            # 타임아웃 적용
            if background_task.timeout:
                task_result = await asyncio.wait_for(
                    background_task.func(*background_task.args, **background_task.kwargs),
                    timeout=background_task.timeout
                )
            else:
                task_result = await background_task.func(
                    *background_task.args, **background_task.kwargs
                )

            # 성공 처리
            result.status = TaskStatus.COMPLETED
            result.result = task_result
            result.end_time = datetime.utcnow()
            result.duration_seconds = (
                result.end_time - result.start_time
            ).total_seconds()

            logger.info(
                f"작업 완료: {background_task.name} ({task_id}) - "
                f"소요시간: {result.duration_seconds:.2f}초"
            )

            return task_result

        except asyncio.TimeoutError:
            error_msg = f"작업 타임아웃: {background_task.timeout}초"
            logger.error(f"작업 타임아웃: {background_task.name} ({task_id})")
            await self._handle_task_failure(task_id, background_task, error_msg)
            raise

        except asyncio.CancelledError:
            logger.info(f"작업 취소됨: {background_task.name} ({task_id})")
            result.status = TaskStatus.CANCELLED
            result.end_time = datetime.utcnow()
            raise

        except Exception as e:
            error_msg = str(e)
            logger.error(f"작업 실행 오류: {background_task.name} ({task_id}) - {error_msg}")
            await self._handle_task_failure(task_id, background_task, error_msg)
            raise

    async def _handle_task_failure(
        self,
        task_id: str,
        background_task: BackgroundTask,
        error_msg: str
    ) -> None:
        """작업 실패 처리"""
        result = self._results[task_id]
        result.retry_count += 1

        # 재시도 가능한지 확인
        if result.retry_count <= background_task.max_retries:
            logger.info(
                f"작업 재시도 예약: {background_task.name} ({task_id}) - "
                f"재시도 횟수: {result.retry_count}/{background_task.max_retries}"
            )

            result.status = TaskStatus.RETRYING
            result.error = error_msg

            # 재시도 스케줄링
            retry_at = datetime.utcnow() + timedelta(seconds=background_task.retry_delay)
            background_task.scheduled_at = retry_at

            # 작업을 다시 대기 큐에 추가
            self._tasks[task_id] = background_task

        else:
            logger.error(
                f"작업 최종 실패: {background_task.name} ({task_id}) - "
                f"최대 재시도 횟수 초과"
            )

            result.status = TaskStatus.FAILED
            result.error = error_msg
            result.end_time = datetime.utcnow()
            result.duration_seconds = (
                result.end_time - result.start_time
            ).total_seconds()

    def _task_completed(self, task_id: str, task: asyncio.Task) -> None:
        """작업 완료 콜백"""
        # 실행 중 목록에서 제거
        self._running_tasks.pop(task_id, None)

        # 재시도가 아닌 경우 대기 목록에서 제거
        result = self._results.get(task_id)
        if result and result.status not in [TaskStatus.RETRYING]:
            self._tasks.pop(task_id, None)

    async def _cleanup_loop(self) -> None:
        """정리 작업 루프"""
        logger.info("백그라운드 작업 정리 루프 시작")

        try:
            while self._is_running:
                await self._cleanup_old_results()
                await asyncio.sleep(self.cleanup_interval)

        except asyncio.CancelledError:
            logger.info("백그라운드 작업 정리 루프 취소됨")
        except Exception as e:
            logger.error(f"백그라운드 작업 정리 루프 오류: {e}")
        finally:
            logger.info("백그라운드 작업 정리 루프 종료")

    async def _cleanup_old_results(self) -> None:
        """오래된 결과 정리"""
        cutoff_time = datetime.utcnow() - timedelta(seconds=self.max_result_age)
        cleaned_count = 0

        for task_id, result in list(self._results.items()):
            # 완료/실패/취소된 작업만 정리
            if result.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                continue

            # 종료 시간이 있고 오래된 경우 정리
            if result.end_time and result.end_time < cutoff_time:
                del self._results[task_id]
                self._tasks.pop(task_id, None)  # 혹시 남아있을 수 있음
                cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"오래된 작업 결과 {cleaned_count}개 정리 완료")

        self._last_cleanup = datetime.utcnow().isoformat()


# 전역 실행기 인스턴스
_executor_instance: Optional[BackgroundTaskExecutor] = None


def get_background_executor() -> BackgroundTaskExecutor:
    """백그라운드 작업 실행기 인스턴스 반환"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = BackgroundTaskExecutor()
    return _executor_instance


async def start_background_executor() -> None:
    """백그라운드 작업 실행기 시작 (애플리케이션 시작 시 호출)"""
    executor = get_background_executor()
    await executor.start()


async def stop_background_executor() -> None:
    """백그라운드 작업 실행기 종료 (애플리케이션 종료 시 호출)"""
    global _executor_instance
    if _executor_instance:
        await _executor_instance.stop()
        _executor_instance = None


# 편의 함수들

async def run_ssl_check_task(website_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """SSL 체크 작업 실행"""
    async with get_async_session() as session:
        ssl_service = SSLService(session)

        if website_ids:
            # 특정 웹사이트들 체크
            uuid_ids = [uuid.UUID(id_str) for id_str in website_ids]
            result = await ssl_service.bulk_ssl_check_by_ids(uuid_ids)
        else:
            # 모든 활성 웹사이트 체크
            result = await ssl_service.bulk_ssl_check(active_only=True)

        return result


async def run_notification_task(notification_days: Optional[List[int]] = None) -> Dict[str, Any]:
    """만료 알림 작업 실행"""
    async with get_async_session() as session:
        notification_service = NotificationService(
            session=session,
            notification_days=notification_days or [30, 14, 7, 3, 1]
        )

        result = await notification_service.send_expiry_notifications()
        return result


def submit_ssl_check(
    website_ids: Optional[List[str]] = None,
    priority: TaskPriority = TaskPriority.NORMAL
) -> str:
    """SSL 체크 작업 제출"""
    executor = get_background_executor()
    return executor.submit_task(
        run_ssl_check_task,
        website_ids,
        name="SSL Certificate Check",
        priority=priority,
        timeout=600.0  # 10분
    )


def submit_notification_task(
    notification_days: Optional[List[int]] = None,
    priority: TaskPriority = TaskPriority.HIGH
) -> str:
    """만료 알림 작업 제출"""
    executor = get_background_executor()
    return executor.submit_task(
        run_notification_task,
        notification_days,
        name="SSL Expiry Notifications",
        priority=priority,
        timeout=300.0  # 5분
    )