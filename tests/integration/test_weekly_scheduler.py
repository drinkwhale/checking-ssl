"""
주간 스케줄러 SSL 일괄 체크 통합 테스트

이 테스트는 사용자 스토리를 검증합니다:
- 주 1회 자동으로 모든 활성 웹사이트의 SSL 인증서를 체크한다
- 배치 처리로 효율적으로 여러 사이트를 동시에 체크한다
- 스케줄러 오류 복구 메커니즘이 작동한다
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.website import Website
from src.models.ssl_certificate import SSLCertificate, SSLStatus
from src.services.ssl_service import SSLService
from src.scheduler import SSLScheduler


class TestWeeklySchedulerFlow:
    """주간 SSL 체크 스케줄러 플로우 테스트"""

    @pytest.mark.asyncio
    async def test_weekly_ssl_check_updates_all_active_websites(
        self,
        db_session: AsyncSession,
        multiple_active_websites: list[Website],
    ):
        """주간 SSL 체크가 모든 활성 웹사이트를 업데이트하는지 테스트"""
        # Given: 여러 활성 웹사이트
        website_count = len(multiple_active_websites)
        assert website_count >= 3

        # When: 주간 SSL 체크 실행
        ssl_service = SSLService(db_session)
        scheduler = SSLScheduler(ssl_service)
        await scheduler.run_weekly_ssl_check()

        # Then: 모든 활성 웹사이트의 SSL 인증서가 업데이트됨
        for website in multiple_active_websites:
            ssl_certs = await db_session.execute(
                "SELECT * FROM ssl_certificates WHERE website_id = :website_id ORDER BY created_at DESC",
                {"website_id": website.id},
            )
            ssl_records = ssl_certs.fetchall()
            assert len(ssl_records) >= 1

            # And: 최신 SSL 인증서의 last_checked가 업데이트됨
            latest_ssl = ssl_records[0]
            time_diff = datetime.utcnow() - latest_ssl.last_checked
            assert time_diff.total_seconds() < 60  # 1분 이내에 체크됨

    @pytest.mark.asyncio
    async def test_weekly_ssl_check_skips_inactive_websites(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        inactive_website: Website,
    ):
        """주간 SSL 체크가 비활성 웹사이트를 건너뛰는지 테스트"""
        # Given: 활성/비활성 웹사이트
        assert sample_website.is_active is True
        assert inactive_website.is_active is False

        # When: 주간 SSL 체크 실행
        ssl_service = SSLService(db_session)
        scheduler = SSLScheduler(ssl_service)
        result = await scheduler.run_weekly_ssl_check()

        # Then: 처리 결과에 활성 웹사이트만 포함됨
        assert result["total_processed"] >= 1
        assert result["active_websites_only"] is True

        # And: 활성 웹사이트는 체크됨
        active_ssl_certs = await db_session.execute(
            "SELECT * FROM ssl_certificates WHERE website_id = :website_id",
            {"website_id": sample_website.id},
        )
        assert len(active_ssl_certs.fetchall()) >= 1

        # And: 비활성 웹사이트는 체크되지 않음 (기존 레코드 유지)
        inactive_ssl_certs = await db_session.execute(
            "SELECT * FROM ssl_certificates WHERE website_id = :website_id",
            {"website_id": inactive_website.id},
        )
        inactive_records = inactive_ssl_certs.fetchall()
        if inactive_records:
            # 기존 레코드가 있다면 last_checked가 오래된 것이어야 함
            latest_inactive_ssl = inactive_records[0]
            time_diff = datetime.utcnow() - latest_inactive_ssl.last_checked
            assert time_diff.total_seconds() > 60  # 1분 이상 전에 체크됨

    @pytest.mark.asyncio
    async def test_concurrent_ssl_checks_with_limit(
        self,
        db_session: AsyncSession,
        many_websites: list[Website],  # 10개 이상의 웹사이트
    ):
        """동시 SSL 체크 제한 테스트"""
        # Given: 많은 웹사이트 (동시 처리 제한 테스트용)
        website_count = len(many_websites)
        assert website_count >= 10

        # When: 동시 처리 제한을 5개로 설정하고 SSL 체크 실행
        with patch("src.services.ssl_service.MAX_CONCURRENT_CHECKS", 5):
            ssl_service = SSLService(db_session)
            start_time = datetime.utcnow()
            result = await ssl_service.check_all_websites_ssl()
            end_time = datetime.utcnow()

        # Then: 모든 웹사이트가 처리됨
        assert result["total_processed"] == website_count
        assert result["successful_checks"] >= website_count * 0.8  # 80% 이상 성공

        # And: 처리 시간이 순차 처리보다 빠름 (동시 처리 효과)
        processing_time = (end_time - start_time).total_seconds()
        max_expected_time = website_count * 2  # 웹사이트당 최대 2초 가정
        assert processing_time < max_expected_time

    @pytest.mark.asyncio
    async def test_ssl_check_error_recovery(
        self,
        db_session: AsyncSession,
        multiple_websites_with_issues: list[Website],
    ):
        """SSL 체크 오류 복구 메커니즘 테스트"""
        # Given: 일부 문제가 있는 웹사이트들
        problematic_urls = [w for w in multiple_websites_with_issues if "timeout" in w.url]
        normal_urls = [w for w in multiple_websites_with_issues if "timeout" not in w.url]

        # When: SSL 체크 실행 (일부 사이트에서 오류 발생 예상)
        ssl_service = SSLService(db_session)
        result = await ssl_service.check_all_websites_ssl()

        # Then: 오류가 있어도 전체 작업이 중단되지 않음
        assert result["total_processed"] == len(multiple_websites_with_issues)
        assert result["failed_checks"] >= len(problematic_urls)

        # And: 정상 웹사이트는 성공적으로 처리됨
        for website in normal_urls:
            ssl_certs = await db_session.execute(
                "SELECT * FROM ssl_certificates WHERE website_id = :website_id ORDER BY created_at DESC",
                {"website_id": website.id},
            )
            ssl_records = ssl_certs.fetchall()
            assert len(ssl_records) >= 1

        # And: 문제 있는 웹사이트는 오류 상태로 기록됨
        for website in problematic_urls:
            ssl_certs = await db_session.execute(
                "SELECT * FROM ssl_certificates WHERE website_id = :website_id ORDER BY created_at DESC",
                {"website_id": website.id},
            )
            ssl_records = ssl_certs.fetchall()
            if ssl_records:
                latest_ssl = ssl_records[0]
                assert latest_ssl.status in [SSLStatus.INVALID, SSLStatus.UNKNOWN]

    @pytest.mark.asyncio
    async def test_scheduler_cron_job_configuration(self):
        """스케줄러 크론 작업 설정 테스트"""
        # Given: 스케줄러 인스턴스
        ssl_service = MagicMock()
        scheduler = SSLScheduler(ssl_service)

        # When: 스케줄러 시작
        await scheduler.start()

        # Then: 크론 작업이 등록됨
        jobs = scheduler.get_jobs()
        ssl_check_jobs = [job for job in jobs if "ssl_check" in job.id]
        assert len(ssl_check_jobs) >= 1

        # And: 크론 표현식이 올바름 (매주 월요일 오전 9시)
        ssl_job = ssl_check_jobs[0]
        trigger = ssl_job.trigger
        assert trigger.fields[4].expressions[0] == 1  # 월요일 (0=월요일)
        assert trigger.fields[2].expressions[0] == 9  # 오전 9시

        # Cleanup
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_scheduler_job_persistence_after_restart(
        self,
        db_session: AsyncSession,
    ):
        """스케줄러 재시작 후 작업 지속성 테스트"""
        # Given: 스케줄러 시작 및 작업 등록
        ssl_service = SSLService(db_session)
        scheduler1 = SSLScheduler(ssl_service)
        await scheduler1.start()

        initial_jobs = scheduler1.get_jobs()
        initial_job_count = len(initial_jobs)

        # When: 스케줄러 재시작
        await scheduler1.stop()
        scheduler2 = SSLScheduler(ssl_service)
        await scheduler2.start()

        # Then: 작업이 복원됨
        restored_jobs = scheduler2.get_jobs()
        assert len(restored_jobs) == initial_job_count

        # Cleanup
        await scheduler2.stop()

    @pytest.mark.asyncio
    async def test_ssl_check_performance_monitoring(
        self,
        db_session: AsyncSession,
        multiple_active_websites: list[Website],
    ):
        """SSL 체크 성능 모니터링 테스트"""
        # Given: 여러 활성 웹사이트
        website_count = len(multiple_active_websites)

        # When: SSL 체크 실행 및 성능 측정
        ssl_service = SSLService(db_session)
        start_time = datetime.utcnow()
        result = await ssl_service.check_all_websites_ssl()
        end_time = datetime.utcnow()

        # Then: 성능 요구사항 충족 (웹사이트당 10초 이내)
        total_time = (end_time - start_time).total_seconds()
        max_allowed_time = website_count * 10
        assert total_time < max_allowed_time

        # And: 성능 메트릭이 결과에 포함됨
        assert "processing_time_seconds" in result
        assert "average_check_time" in result
        assert result["average_check_time"] < 10.0

    @pytest.mark.asyncio
    async def test_scheduler_graceful_shutdown(
        self,
        db_session: AsyncSession,
    ):
        """스케줄러 정상 종료 테스트"""
        # Given: 실행 중인 스케줄러
        ssl_service = SSLService(db_session)
        scheduler = SSLScheduler(ssl_service)
        await scheduler.start()

        # When: 진행 중인 작업이 있는 상태에서 종료 요청
        # 시뮬레이션: 장시간 실행되는 작업 시작
        long_running_task = asyncio.create_task(asyncio.sleep(5))

        # Then: 정상적으로 종료됨
        shutdown_start = datetime.utcnow()
        await scheduler.stop()
        shutdown_end = datetime.utcnow()

        # And: 종료 시간이 합리적임 (최대 10초)
        shutdown_time = (shutdown_end - shutdown_start).total_seconds()
        assert shutdown_time < 10.0

        # Cleanup
        if not long_running_task.done():
            long_running_task.cancel()

    @pytest.mark.asyncio
    async def test_ssl_check_result_notification_integration(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        mock_teams_webhook: AsyncMock,
    ):
        """SSL 체크 결과 알림 통합 테스트"""
        # Given: SSL 인증서가 곧 만료되는 웹사이트
        expiry_date = datetime.utcnow() + timedelta(days=7)
        ssl_cert = SSLCertificate(
            website_id=sample_website.id,
            issuer="Test CA",
            subject=f"CN={sample_website.url}",
            serial_number="123456789",
            issued_date=datetime.utcnow() - timedelta(days=83),
            expiry_date=expiry_date,
            fingerprint="test_fingerprint",
            status=SSLStatus.VALID,
            last_checked=datetime.utcnow() - timedelta(days=1),  # 어제 체크됨
        )
        db_session.add(ssl_cert)
        await db_session.commit()

        # When: 주간 SSL 체크 실행 (알림 포함)
        ssl_service = SSLService(db_session)
        scheduler = SSLScheduler(ssl_service, enable_notifications=True)
        result = await scheduler.run_weekly_ssl_check()

        # Then: SSL 체크가 성공하고 알림이 발송됨
        assert result["total_processed"] >= 1
        assert result["notifications_sent"] >= 1

        # And: Teams 웹훅이 호출됨
        mock_teams_webhook.assert_called()
        call_args = mock_teams_webhook.call_args
        message_data = call_args[1]["json"]
        assert sample_website.url in str(message_data)