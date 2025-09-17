"""
APScheduler 설정 및 주간 SSL 체크 스케줄러

정기적인 SSL 인증서 체크와 만료 알림을 자동화하는 스케줄러입니다.
"""

import asyncio
import logging
import os
from datetime import datetime, time
from typing import Optional, Dict, Any, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from .database import get_async_session
from .services.ssl_service import SSLService, SSLServiceError
from .services.notification_service import NotificationService, NotificationServiceError


# 로깅 설정
logger = logging.getLogger(__name__)


class SchedulerService:
    """SSL 모니터링 스케줄러 서비스"""

    def __init__(
        self,
        weekly_check_day: int = 1,  # 월요일 (0=월요일, 6=일요일)
        weekly_check_time: str = "09:00",  # 09:00 AM
        notification_check_interval: int = 24,  # 24시간마다
        teams_webhook_url: Optional[str] = None,
        max_concurrent_jobs: int = 3
    ):
        """
        Args:
            weekly_check_day: 주간 체크 요일 (0=월요일, 6=일요일)
            weekly_check_time: 주간 체크 시간 (HH:MM 형식)
            notification_check_interval: 알림 체크 간격 (시간)
            teams_webhook_url: Teams 웹훅 URL
            max_concurrent_jobs: 최대 동시 실행 작업 수
        """
        self.weekly_check_day = weekly_check_day
        self.weekly_check_time = weekly_check_time
        self.notification_check_interval = notification_check_interval
        self.teams_webhook_url = teams_webhook_url or os.getenv("TEAMS_WEBHOOK_URL")
        self.max_concurrent_jobs = max_concurrent_jobs

        # 스케줄러 설정
        self.scheduler = AsyncIOScheduler(
            jobstores={
                'default': MemoryJobStore()
            },
            executors={
                'default': AsyncIOExecutor()
            },
            job_defaults={
                'coalesce': False,  # 놓친 실행을 누적하지 않음
                'max_instances': 1,  # 같은 작업은 하나만 동시 실행
                'misfire_grace_time': 30  # 30초 안에 실행되지 않으면 skip
            }
        )

        # 이벤트 리스너 등록
        self.scheduler.add_listener(
            self._job_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        self._is_running = False

    async def start(self) -> None:
        """스케줄러 시작"""
        if self._is_running:
            logger.warning("스케줄러가 이미 실행 중입니다")
            return

        try:
            logger.info("SSL 모니터링 스케줄러 시작 중...")

            # 주간 SSL 체크 작업 등록
            await self._schedule_weekly_ssl_check()

            # 만료 알림 체크 작업 등록
            await self._schedule_expiry_notifications()

            # 헬스체크 작업 등록
            await self._schedule_health_check()

            # 스케줄러 시작
            self.scheduler.start()
            self._is_running = True

            logger.info("SSL 모니터링 스케줄러 시작 완료")

        except Exception as e:
            logger.error(f"스케줄러 시작 실패: {e}")
            raise

    async def stop(self) -> None:
        """스케줄러 종료"""
        if not self._is_running:
            logger.warning("스케줄러가 실행 중이 아닙니다")
            return

        try:
            logger.info("SSL 모니터링 스케줄러 종료 중...")

            # 대기 중인 작업들이 완료될 때까지 대기
            self.scheduler.shutdown(wait=True)
            self._is_running = False

            logger.info("SSL 모니터링 스케줄러 종료 완료")

        except Exception as e:
            logger.error(f"스케줄러 종료 실패: {e}")
            raise

    async def _schedule_weekly_ssl_check(self) -> None:
        """주간 SSL 체크 작업 스케줄링"""
        try:
            # 시간 파싱
            hour, minute = map(int, self.weekly_check_time.split(':'))

            # 크론 트리거 생성 (매주 지정된 요일과 시간에 실행)
            trigger = CronTrigger(
                day_of_week=self.weekly_check_day,
                hour=hour,
                minute=minute,
                timezone='Asia/Seoul'  # 한국 시간 기준
            )

            # 작업 등록
            self.scheduler.add_job(
                self._run_weekly_ssl_check,
                trigger=trigger,
                id='weekly_ssl_check',
                name='주간 SSL 인증서 체크',
                replace_existing=True
            )

            logger.info(
                f"주간 SSL 체크 작업 등록 완료: 매주 {['월', '화', '수', '목', '금', '토', '일'][self.weekly_check_day]}요일 "
                f"{self.weekly_check_time}"
            )

        except Exception as e:
            logger.error(f"주간 SSL 체크 작업 등록 실패: {e}")
            raise

    async def _schedule_expiry_notifications(self) -> None:
        """만료 알림 체크 작업 스케줄링"""
        try:
            # 인터벌 트리거 생성 (지정된 시간마다 실행)
            trigger = IntervalTrigger(
                hours=self.notification_check_interval,
                timezone='Asia/Seoul'
            )

            # 작업 등록
            self.scheduler.add_job(
                self._run_expiry_notifications,
                trigger=trigger,
                id='expiry_notifications',
                name='SSL 만료 알림 체크',
                replace_existing=True
            )

            logger.info(f"만료 알림 체크 작업 등록 완료: {self.notification_check_interval}시간마다")

        except Exception as e:
            logger.error(f"만료 알림 체크 작업 등록 실패: {e}")
            raise

    async def _schedule_health_check(self) -> None:
        """스케줄러 헬스체크 작업 등록"""
        try:
            # 매시간 헬스체크 실행
            trigger = IntervalTrigger(
                hours=1,
                timezone='Asia/Seoul'
            )

            # 작업 등록
            self.scheduler.add_job(
                self._run_health_check,
                trigger=trigger,
                id='scheduler_health_check',
                name='스케줄러 헬스체크',
                replace_existing=True
            )

            logger.info("스케줄러 헬스체크 작업 등록 완료: 1시간마다")

        except Exception as e:
            logger.error(f"헬스체크 작업 등록 실패: {e}")
            raise

    async def _run_weekly_ssl_check(self) -> Dict[str, Any]:
        """주간 SSL 체크 실행"""
        logger.info("주간 SSL 체크 작업 시작")
        start_time = datetime.utcnow()

        try:
            async with get_async_session() as session:
                ssl_service = SSLService(session)

                # 모든 활성 웹사이트의 SSL 인증서 체크
                result = await ssl_service.bulk_ssl_check(
                    active_only=True,
                    max_concurrent=self.max_concurrent_jobs
                )

                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()

                logger.info(
                    f"주간 SSL 체크 완료: {result['successful_checks']}/{result['total_websites']} 성공, "
                    f"소요시간: {duration:.2f}초"
                )

                return {
                    "job_type": "weekly_ssl_check",
                    "status": "completed",
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_seconds": duration,
                    "result": result
                }

        except Exception as e:
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.error(f"주간 SSL 체크 실패: {e}")

            return {
                "job_type": "weekly_ssl_check",
                "status": "failed",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "error": str(e)
            }

    async def _run_expiry_notifications(self) -> Dict[str, Any]:
        """만료 알림 체크 실행"""
        logger.info("SSL 만료 알림 체크 작업 시작")
        start_time = datetime.utcnow()

        try:
            async with get_async_session() as session:
                notification_service = NotificationService(
                    session=session,
                    webhook_url=self.teams_webhook_url,
                    notification_days=[30, 14, 7, 3, 1]  # 만료 30, 14, 7, 3, 1일 전 알림
                )

                # 만료 임박 인증서 알림 발송
                result = await notification_service.send_expiry_notifications()

                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()

                logger.info(
                    f"만료 알림 체크 완료: {result.get('notifications_sent', 0)}개 알림 발송, "
                    f"소요시간: {duration:.2f}초"
                )

                return {
                    "job_type": "expiry_notifications",
                    "status": "completed",
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_seconds": duration,
                    "result": result
                }

        except Exception as e:
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.error(f"만료 알림 체크 실패: {e}")

            return {
                "job_type": "expiry_notifications",
                "status": "failed",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "error": str(e)
            }

    async def _run_health_check(self) -> Dict[str, Any]:
        """스케줄러 헬스체크 실행"""
        logger.debug("스케줄러 헬스체크 시작")
        start_time = datetime.utcnow()

        try:
            # 스케줄러 상태 확인
            running_jobs = len(self.scheduler.get_jobs())
            next_run_times = []

            for job in self.scheduler.get_jobs():
                if job.next_run_time:
                    next_run_times.append({
                        "job_id": job.id,
                        "job_name": job.name,
                        "next_run_time": job.next_run_time.isoformat()
                    })

            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.debug(f"스케줄러 헬스체크 완료: {running_jobs}개 작업 실행 중")

            return {
                "job_type": "health_check",
                "status": "completed",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "result": {
                    "running_jobs": running_jobs,
                    "next_run_times": next_run_times,
                    "scheduler_running": self.scheduler.running
                }
            }

        except Exception as e:
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            logger.error(f"스케줄러 헬스체크 실패: {e}")

            return {
                "job_type": "health_check",
                "status": "failed",
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "error": str(e)
            }

    def _job_listener(self, event: JobExecutionEvent) -> None:
        """작업 이벤트 리스너"""
        if event.exception:
            logger.error(
                f"스케줄된 작업 실행 실패: {event.job_id} - {event.exception}"
            )
        else:
            logger.info(
                f"스케줄된 작업 실행 완료: {event.job_id} - "
                f"소요시간: {event.scheduled_run_time}"
            )

    def get_job_status(self) -> Dict[str, Any]:
        """현재 작업 상태 조회"""
        if not self._is_running:
            return {
                "scheduler_running": False,
                "jobs": []
            }

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "func": job.func.__name__
            })

        return {
            "scheduler_running": self.scheduler.running,
            "jobs": jobs,
            "total_jobs": len(jobs)
        }

    async def trigger_job_now(self, job_id: str) -> Dict[str, Any]:
        """특정 작업을 즉시 실행"""
        try:
            job = self.scheduler.get_job(job_id)
            if not job:
                raise ValueError(f"작업을 찾을 수 없습니다: {job_id}")

            logger.info(f"작업 수동 실행: {job_id}")

            # 작업 함수 직접 호출
            if job_id == 'weekly_ssl_check':
                result = await self._run_weekly_ssl_check()
            elif job_id == 'expiry_notifications':
                result = await self._run_expiry_notifications()
            elif job_id == 'scheduler_health_check':
                result = await self._run_health_check()
            else:
                raise ValueError(f"지원하지 않는 작업입니다: {job_id}")

            return {
                "triggered": True,
                "job_id": job_id,
                "result": result
            }

        except Exception as e:
            logger.error(f"작업 수동 실행 실패: {job_id} - {e}")
            return {
                "triggered": False,
                "job_id": job_id,
                "error": str(e)
            }


# 전역 스케줄러 인스턴스
_scheduler_instance: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    """스케줄러 인스턴스 반환"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SchedulerService()
    return _scheduler_instance


async def start_scheduler() -> None:
    """스케줄러 시작 (애플리케이션 시작 시 호출)"""
    scheduler = get_scheduler()
    await scheduler.start()


async def stop_scheduler() -> None:
    """스케줄러 종료 (애플리케이션 종료 시 호출)"""
    global _scheduler_instance
    if _scheduler_instance:
        await _scheduler_instance.stop()
        _scheduler_instance = None