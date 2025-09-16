"""
만료 인증서 Teams 알림 통합 테스트

이 테스트는 사용자 스토리를 검증합니다:
- 인증서 만료 30일/7일/1일 전에 Teams 알림이 발송된다
- 인증서 오류 발생 시 즉시 알림이 발송된다
- 알림 메시지 형식이 적절하다
"""

import pytest
import httpx
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.website import Website
from src.models.ssl_certificate import SSLCertificate, SSLStatus
from src.services.notification_service import NotificationService


class TestTeamsNotificationFlow:
    """Teams 알림 플로우 테스트"""

    @pytest.mark.asyncio
    async def test_expiring_certificate_sends_teams_notification(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        mock_teams_webhook: AsyncMock,
    ):
        """만료 임박 인증서 Teams 알림 발송 테스트"""
        # Given: 30일 후 만료되는 SSL 인증서
        expiry_date = datetime.utcnow() + timedelta(days=30)
        ssl_cert = SSLCertificate(
            website_id=sample_website.id,
            issuer="Test CA",
            subject=f"CN={sample_website.url}",
            serial_number="123456789",
            issued_date=datetime.utcnow() - timedelta(days=60),
            expiry_date=expiry_date,
            fingerprint="test_fingerprint",
            status=SSLStatus.VALID,
            last_checked=datetime.utcnow(),
        )
        db_session.add(ssl_cert)
        await db_session.commit()

        # When: 만료 알림 서비스 실행
        notification_service = NotificationService(db_session)
        await notification_service.check_and_send_expiry_notifications()

        # Then: Teams 웹훅이 호출됨
        mock_teams_webhook.assert_called_once()
        call_args = mock_teams_webhook.call_args
        message_data = call_args[1]["json"]

        # And: 알림 메시지에 필수 정보가 포함됨
        assert sample_website.url in str(message_data)
        assert "30일" in str(message_data) or "30 days" in str(message_data)
        assert "만료" in str(message_data) or "expir" in str(message_data).lower()

    @pytest.mark.asyncio
    async def test_critical_expiry_notification_format(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        mock_teams_webhook: AsyncMock,
    ):
        """중요 만료 알림 (1일 전) 메시지 형식 테스트"""
        # Given: 1일 후 만료되는 SSL 인증서
        expiry_date = datetime.utcnow() + timedelta(days=1)
        ssl_cert = SSLCertificate(
            website_id=sample_website.id,
            issuer="Test CA",
            subject=f"CN={sample_website.url}",
            serial_number="123456789",
            issued_date=datetime.utcnow() - timedelta(days=89),
            expiry_date=expiry_date,
            fingerprint="test_fingerprint",
            status=SSLStatus.VALID,
            last_checked=datetime.utcnow(),
        )
        db_session.add(ssl_cert)
        await db_session.commit()

        # When: 긴급 만료 알림 서비스 실행
        notification_service = NotificationService(db_session)
        await notification_service.check_and_send_expiry_notifications()

        # Then: Teams 웹훅이 호출됨
        mock_teams_webhook.assert_called_once()
        call_args = mock_teams_webhook.call_args
        message_data = call_args[1]["json"]

        # And: 긴급 알림 표시가 있음
        message_str = str(message_data)
        assert any(
            keyword in message_str.lower()
            for keyword in ["urgent", "긴급", "critical", "위험"]
        )
        assert "1" in message_str  # 1일 표시

    @pytest.mark.asyncio
    async def test_ssl_error_immediate_notification(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        mock_teams_webhook: AsyncMock,
    ):
        """SSL 오류 즉시 알림 테스트"""
        # Given: SSL 오류가 발생한 인증서
        ssl_cert = SSLCertificate(
            website_id=sample_website.id,
            issuer="",
            subject="",
            serial_number="",
            issued_date=datetime.utcnow(),
            expiry_date=datetime.utcnow() + timedelta(days=90),
            fingerprint="",
            status=SSLStatus.INVALID,
            last_checked=datetime.utcnow(),
        )
        db_session.add(ssl_cert)
        await db_session.commit()

        # When: SSL 오류 알림 서비스 실행
        notification_service = NotificationService(db_session)
        await notification_service.send_ssl_error_notification(sample_website, "Connection timeout")

        # Then: Teams 웹훅이 호출됨
        mock_teams_webhook.assert_called_once()
        call_args = mock_teams_webhook.call_args
        message_data = call_args[1]["json"]

        # And: 오류 알림 정보가 포함됨
        message_str = str(message_data)
        assert sample_website.url in message_str
        assert any(
            keyword in message_str.lower()
            for keyword in ["error", "오류", "failed", "실패"]
        )
        assert "Connection timeout" in message_str

    @pytest.mark.asyncio
    async def test_notification_disabled_no_send(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        mock_teams_webhook: AsyncMock,
    ):
        """알림 비활성화 시 발송되지 않는지 테스트"""
        # Given: 알림이 비활성화된 설정
        with patch("src.services.notification_service.settings.NOTIFICATION_ENABLED", False):
            # And: 만료 임박 인증서
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
                last_checked=datetime.utcnow(),
            )
            db_session.add(ssl_cert)
            await db_session.commit()

            # When: 알림 서비스 실행
            notification_service = NotificationService(db_session)
            await notification_service.check_and_send_expiry_notifications()

            # Then: Teams 웹훅이 호출되지 않음
            mock_teams_webhook.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_expiring_certificates_batch_notification(
        self,
        db_session: AsyncSession,
        multiple_websites: list[Website],
        mock_teams_webhook: AsyncMock,
    ):
        """여러 만료 임박 인증서 일괄 알림 테스트"""
        # Given: 여러 웹사이트의 만료 임박 인증서
        for i, website in enumerate(multiple_websites[:3]):
            days_until_expiry = [30, 7, 1][i]  # 각각 다른 만료일
            expiry_date = datetime.utcnow() + timedelta(days=days_until_expiry)
            ssl_cert = SSLCertificate(
                website_id=website.id,
                issuer=f"Test CA {i}",
                subject=f"CN={website.url}",
                serial_number=f"12345678{i}",
                issued_date=datetime.utcnow() - timedelta(days=90-days_until_expiry),
                expiry_date=expiry_date,
                fingerprint=f"test_fingerprint_{i}",
                status=SSLStatus.VALID,
                last_checked=datetime.utcnow(),
            )
            db_session.add(ssl_cert)
        await db_session.commit()

        # When: 만료 알림 서비스 실행
        notification_service = NotificationService(db_session)
        await notification_service.check_and_send_expiry_notifications()

        # Then: Teams 웹훅이 여러 번 호출됨 (각 만료 기간별로)
        assert mock_teams_webhook.call_count >= 3

        # And: 각 웹사이트 URL이 알림에 포함됨
        all_calls = [str(call[1]["json"]) for call in mock_teams_webhook.call_args_list]
        for website in multiple_websites[:3]:
            assert any(website.url in call_str for call_str in all_calls)

    @pytest.mark.asyncio
    async def test_teams_webhook_retry_mechanism(
        self,
        db_session: AsyncSession,
        sample_website: Website,
    ):
        """Teams 웹훅 재시도 메커니즘 테스트"""
        # Given: 실패하는 Teams 웹훅
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = [
                httpx.RequestError("Connection failed"),  # 첫 번째 시도 실패
                httpx.RequestError("Connection failed"),  # 두 번째 시도 실패
                httpx.Response(200),  # 세 번째 시도 성공
            ]

            # And: 만료 임박 인증서
            expiry_date = datetime.utcnow() + timedelta(days=30)
            ssl_cert = SSLCertificate(
                website_id=sample_website.id,
                issuer="Test CA",
                subject=f"CN={sample_website.url}",
                serial_number="123456789",
                issued_date=datetime.utcnow() - timedelta(days=60),
                expiry_date=expiry_date,
                fingerprint="test_fingerprint",
                status=SSLStatus.VALID,
                last_checked=datetime.utcnow(),
            )
            db_session.add(ssl_cert)
            await db_session.commit()

            # When: 알림 서비스 실행
            notification_service = NotificationService(db_session)
            result = await notification_service.check_and_send_expiry_notifications()

            # Then: 재시도를 통해 성공함
            assert result is True
            assert mock_post.call_count == 3

    @pytest.mark.asyncio
    async def test_notification_message_korean_formatting(
        self,
        db_session: AsyncSession,
        sample_website: Website,
        mock_teams_webhook: AsyncMock,
    ):
        """한국어 알림 메시지 형식 테스트"""
        # Given: 7일 후 만료되는 SSL 인증서
        expiry_date = datetime.utcnow() + timedelta(days=7)
        ssl_cert = SSLCertificate(
            website_id=sample_website.id,
            issuer="Let's Encrypt",
            subject=f"CN={sample_website.url}",
            serial_number="123456789",
            issued_date=datetime.utcnow() - timedelta(days=83),
            expiry_date=expiry_date,
            fingerprint="test_fingerprint",
            status=SSLStatus.VALID,
            last_checked=datetime.utcnow(),
        )
        db_session.add(ssl_cert)
        await db_session.commit()

        # When: 한국어 알림 설정으로 서비스 실행
        notification_service = NotificationService(db_session, language="ko")
        await notification_service.check_and_send_expiry_notifications()

        # Then: Teams 웹훅이 호출됨
        mock_teams_webhook.assert_called_once()
        call_args = mock_teams_webhook.call_args
        message_data = call_args[1]["json"]

        # And: 한국어 메시지가 포함됨
        message_str = str(message_data)
        korean_keywords = ["SSL", "인증서", "만료", "웹사이트", "일"]
        assert any(keyword in message_str for keyword in korean_keywords)