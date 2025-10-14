"""
Teams 알림 라이브러리

Microsoft Teams 웹훅 통합 및 메시지 포맷을 담당하는 라이브러리입니다.
CLI 인터페이스도 제공합니다.
"""

import asyncio
import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ..models.website import Website
from ..models.ssl_certificate import SSLCertificate, SSLStatus
from ..database import get_async_session, db_manager
from ..lib.settings_manager import SettingsManager


# 로깅 설정
logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """알림 관련 오류"""
    pass


class TeamsWebhookError(NotificationError):
    """Teams 웹훅 오류"""
    pass


class NotificationService:
    """Teams 알림 서비스 클래스"""

    def __init__(
        self,
        session: AsyncSession,
        webhook_url: Optional[str] = None,
        language: str = "ko",
        retry_count: int = 3,
        timeout: int = 30
    ):
        """
        Args:
            session: 데이터베이스 세션
            webhook_url: Teams 웹훅 URL (None이면 DB 설정에서 로드)
            language: 메시지 언어 ('ko', 'en') - DB 설정에서 로드 가능
            retry_count: 재시도 횟수
            timeout: 타임아웃 (초)
        """
        self.session = session
        self.settings_manager = SettingsManager(session)

        # 웹훅 URL: 파라미터 > DB 설정 > 환경변수 순서로 우선순위
        raw_webhook_url = webhook_url or os.getenv("TEAMS_WEBHOOK_URL")
        self.webhook_url = self._fix_powerautomate_api_version(raw_webhook_url)

        self.language = language
        self.retry_count = retry_count
        self.timeout = timeout

        # 알림 설정 기본값 (DB에서 로드 전까지 사용)
        self.notification_enabled = os.getenv("NOTIFICATION_ENABLED", "true").lower() == "true"
        self.notification_days = self._parse_notification_days()

        # DB 설정 로드 상태
        self._settings_loaded = False

    def _fix_powerautomate_api_version(self, webhook_url: Optional[str]) -> Optional[str]:
        """Power Automate 웹훅 URL의 API 버전을 수정

        Power Automate는 api-version=1을 지원하지 않으므로,
        자동으로 지원되는 버전(2024-10-01)으로 변경합니다.

        Args:
            webhook_url: 원본 웹훅 URL

        Returns:
            수정된 웹훅 URL
        """
        if not webhook_url:
            return webhook_url

        # Power Automate URL인 경우에만 처리
        if "powerautomate" in webhook_url or "powerplatform.com" in webhook_url:
            # api-version=1을 api-version=2024-10-01로 변경
            if "api-version=1" in webhook_url:
                webhook_url = webhook_url.replace("api-version=1", "api-version=2024-10-01")
                logger.info("Power Automate API 버전을 1에서 2024-10-01로 자동 수정했습니다")

        return webhook_url

    def _parse_notification_days(self) -> List[int]:
        """알림 발송 일수 파싱

        Returns:
            알림 발송 일수 목록
        """
        days_str = os.getenv("NOTIFICATION_DAYS_BEFORE", "30,7,1")
        try:
            return [int(day.strip()) for day in days_str.split(",")]
        except Exception:
            return [30, 7, 1]  # 기본값

    async def _load_settings_from_db(self) -> None:
        """DB에서 설정 로드

        웹훅 URL, 알림 활성화 여부, 알림 일수, 언어를 DB 설정에서 로드합니다.
        이미 로드된 경우 스킵합니다.
        """
        if self._settings_loaded:
            return

        try:
            # DB에서 설정 조회
            settings = await self.settings_manager.get_settings()

            # 웹훅 URL이 파라미터로 전달되지 않았으면 DB에서 로드
            if not self.webhook_url and settings.webhook_url:
                self.webhook_url = self._fix_powerautomate_api_version(settings.webhook_url)

            # 알림 설정 업데이트
            self.notification_enabled = settings.notification_enabled

            # 알림 일수 파싱
            if settings.notification_days_before:
                try:
                    self.notification_days = [
                        int(day.strip())
                        for day in settings.notification_days_before.split(",")
                    ]
                except Exception:
                    pass  # 기본값 유지

            # 언어 설정
            if settings.notification_language:
                self.language = settings.notification_language

            self._settings_loaded = True
            logger.info("DB 설정 로드 완료")

        except Exception as e:
            logger.warning(f"DB 설정 로드 실패, 기본값 사용: {str(e)}")
            # 실패해도 기본값으로 계속 진행

    async def check_and_send_expiry_notifications(self) -> bool:
        """만료 임박 인증서 체크 및 알림 발송

        Returns:
            발송 성공 여부
        """
        # DB 설정 로드
        await self._load_settings_from_db()

        if not self.notification_enabled:
            logger.info("알림이 비활성화되어 있습니다")
            return True

        if not self.webhook_url:
            logger.warning("Teams 웹훅 URL이 설정되지 않았습니다")
            return False

        try:
            # 만료 임박 인증서 조회
            expiring_certificates = await self._get_expiring_certificates()

            if not expiring_certificates:
                logger.info("만료 임박 인증서가 없습니다")
                return True

            # 일수별로 그룹화하여 알림 발송
            grouped_certs = self._group_certificates_by_expiry_days(expiring_certificates)

            for days, certs in grouped_certs.items():
                await self._send_expiry_notification(certs, days)

            logger.info(f"만료 알림 발송 완료: {len(expiring_certificates)}개 인증서")
            return True

        except Exception as e:
            logger.error(f"만료 알림 발송 실패: {str(e)}")
            return False

    async def _get_expiring_certificates(self) -> List[tuple]:
        """만료 임박 인증서 조회

        Returns:
            (웹사이트, SSL인증서) 튜플 목록
        """
        expiring_certs = []

        for days in self.notification_days:
            # 정확히 N일 후 만료되는 인증서 조회
            target_date = datetime.now(timezone.utc) + timedelta(days=days)
            start_date = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

            result = await self.session.execute(
                select(Website, SSLCertificate)
                .join(SSLCertificate, Website.id == SSLCertificate.website_id)
                .where(
                    and_(
                        Website.is_active == True,
                        SSLCertificate.status == SSLStatus.VALID,
                        SSLCertificate.expiry_date >= start_date,
                        SSLCertificate.expiry_date <= end_date
                    )
                )
                .order_by(SSLCertificate.expiry_date)
            )

            for website, cert in result.all():
                expiring_certs.append((website, cert, days))

        return expiring_certs

    def _group_certificates_by_expiry_days(self, certificates: List[tuple]) -> Dict[int, List[tuple]]:
        """인증서를 만료 일수별로 그룹화

        Args:
            certificates: (웹사이트, SSL인증서, 만료일수) 튜플 목록

        Returns:
            일수별로 그룹화된 인증서 딕셔너리
        """
        grouped = {}
        for website, cert, days in certificates:
            if days not in grouped:
                grouped[days] = []
            grouped[days].append((website, cert))

        return grouped

    async def _send_expiry_notification(self, certificates: List[tuple], days: int) -> bool:
        """만료 알림 발송

        Args:
            certificates: (웹사이트, SSL인증서) 튜플 목록
            days: 만료까지 남은 일수

        Returns:
            발송 성공 여부
        """
        try:
            message = self._create_expiry_message(certificates, days)
            return await self._send_teams_message(message)

        except Exception as e:
            logger.error(f"만료 알림 발송 실패 ({days}일): {str(e)}")
            return False

    def _create_expiry_message(self, certificates: List[tuple], days: int) -> Dict[str, Any]:
        """만료 알림 메시지 생성

        Args:
            certificates: (웹사이트, SSL인증서) 튜플 목록
            days: 만료까지 남은 일수

        Returns:
            Teams 메시지 페이로드
        """
        if self.language == "ko":
            return self._create_korean_expiry_message(certificates, days)
        else:
            return self._create_english_expiry_message(certificates, days)

    def _create_korean_expiry_message(self, certificates: List[tuple], days: int) -> Dict[str, Any]:
        """한국어 만료 알림 메시지 생성"""
        # 긴급도 결정
        if days <= 1:
            urgency = "🚨 긴급"
            theme_color = "FF0000"  # 빨강
        elif days <= 7:
            urgency = "⚠️ 주의"
            theme_color = "FFA500"  # 주황
        else:
            urgency = "📢 알림"
            theme_color = "0078D7"  # 파랑

        # 제목
        title = f"{urgency} SSL 인증서 만료 알림"

        if days == 1:
            subtitle = f"{len(certificates)}개의 SSL 인증서가 내일 만료됩니다!"
        else:
            subtitle = f"{len(certificates)}개의 SSL 인증서가 {days}일 후 만료됩니다."

        # 인증서 목록을 Facts로 구성
        facts = []
        for idx, (website, cert) in enumerate(certificates, 1):
            issuer = cert.issuer.split(",")[0] if "," in cert.issuer else cert.issuer
            facts.append({
                "name": f"[{idx}] {website.name}",
                "value": f"{website.url}"
            })
            facts.append({
                "name": "만료일",
                "value": cert.expiry_date.strftime('%Y년 %m월 %d일 %H:%M')
            })
            facts.append({
                "name": "발급자",
                "value": issuer
            })

        # MessageCard 형식으로 구성
        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"SSL 인증서 만료 알림 ({days}일 전)",
            "themeColor": theme_color,
            "title": title,
            "text": subtitle,
            "sections": [
                {
                    "facts": facts
                }
            ]
        }

        # 대시보드 링크 추가
        dashboard_url = os.getenv("DASHBOARD_URL", "https://ssl-checker.example.com")
        if dashboard_url != "https://ssl-checker.example.com":
            message["potentialAction"] = [
                {
                    "@type": "OpenUri",
                    "name": "SSL 대시보드 확인",
                    "targets": [
                        {
                            "os": "default",
                            "uri": dashboard_url
                        }
                    ]
                }
            ]

        # Power Automate 호환성: attachments 배열 추가
        # 일부 플로우가 attachments를 기대할 수 있음
        message["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.0",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": title,
                            "weight": "bolder",
                            "size": "large"
                        },
                        {
                            "type": "TextBlock",
                            "text": subtitle,
                            "wrap": True
                        }
                    ]
                }
            }
        ]

        return message

    def _create_english_expiry_message(self, certificates: List[tuple], days: int) -> Dict[str, Any]:
        """영어 만료 알림 메시지 생성"""
        # 긴급도 결정
        if days <= 1:
            urgency = "🚨 URGENT"
            theme_color = "FF0000"  # Red
        elif days <= 7:
            urgency = "⚠️ WARNING"
            theme_color = "FFA500"  # Orange
        else:
            urgency = "📢 NOTICE"
            theme_color = "0078D7"  # Blue

        # 제목
        title = f"{urgency} SSL Certificate Expiry Alert"

        if days == 1:
            subtitle = f"{len(certificates)} SSL certificate(s) will expire tomorrow!"
        else:
            subtitle = f"{len(certificates)} SSL certificate(s) will expire in {days} days."

        # 인증서 목록을 Facts로 구성
        facts = []
        for idx, (website, cert) in enumerate(certificates, 1):
            issuer = cert.issuer.split(",")[0] if "," in cert.issuer else cert.issuer
            facts.append({
                "name": f"[{idx}] {website.name}",
                "value": f"{website.url}"
            })
            facts.append({
                "name": "Expiry Date",
                "value": cert.expiry_date.strftime('%Y-%m-%d %H:%M')
            })
            facts.append({
                "name": "Issuer",
                "value": issuer
            })

        # MessageCard 형식으로 구성
        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"SSL Certificate Expiry Alert ({days} days)",
            "themeColor": theme_color,
            "title": title,
            "text": subtitle,
            "sections": [
                {
                    "facts": facts
                }
            ]
        }

        # 대시보드 링크 추가
        dashboard_url = os.getenv("DASHBOARD_URL", "https://ssl-checker.example.com")
        if dashboard_url != "https://ssl-checker.example.com":
            message["potentialAction"] = [
                {
                    "@type": "OpenUri",
                    "name": "Check SSL Dashboard",
                    "targets": [
                        {
                            "os": "default",
                            "uri": dashboard_url
                        }
                    ]
                }
            ]

        # Power Automate 호환성: attachments 배열 추가
        message["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.0",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": title,
                            "weight": "bolder",
                            "size": "large"
                        },
                        {
                            "type": "TextBlock",
                            "text": subtitle,
                            "wrap": True
                        }
                    ]
                }
            }
        ]

        return message

    async def send_ssl_error_notification(self, website: Website, error_message: str) -> bool:
        """SSL 오류 즉시 알림 발송

        Args:
            website: 웹사이트 객체
            error_message: 오류 메시지

        Returns:
            발송 성공 여부
        """
        if not self.notification_enabled or not self.webhook_url:
            return False

        try:
            message = self._create_error_message(website, error_message)
            return await self._send_teams_message(message)

        except Exception as e:
            logger.error(f"SSL 오류 알림 발송 실패: {website.url} - {str(e)}")
            return False

    def _create_error_message(self, website: Website, error_message: str) -> Dict[str, Any]:
        """SSL 오류 메시지 생성

        Args:
            website: 웹사이트 객체
            error_message: 오류 메시지

        Returns:
            Teams 메시지 페이로드
        """
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if self.language == "ko":
            title = "🚨 SSL 인증서 오류 발생"
            subtitle = f"{website.name} 웹사이트에서 SSL 오류가 발생했습니다."
            facts = [
                {"name": "웹사이트", "value": f"{website.name}"},
                {"name": "URL", "value": website.url},
                {"name": "오류 내용", "value": error_message},
                {"name": "발생 시간", "value": current_time}
            ]
        else:
            title = "🚨 SSL Certificate Error"
            subtitle = f"SSL error occurred on {website.name} website."
            facts = [
                {"name": "Website", "value": f"{website.name}"},
                {"name": "URL", "value": website.url},
                {"name": "Error Details", "value": error_message},
                {"name": "Occurred At", "value": current_time}
            ]

        # MessageCard 형식으로 구성
        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": "SSL Certificate Error",
            "themeColor": "FF0000",  # 빨강
            "title": title,
            "text": subtitle,
            "sections": [
                {
                    "facts": facts
                }
            ]
        }

        # Power Automate 호환성: attachments 배열 추가
        message["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.0",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": title,
                            "weight": "bolder",
                            "size": "large",
                            "color": "attention"
                        },
                        {
                            "type": "TextBlock",
                            "text": subtitle,
                            "wrap": True
                        }
                    ]
                }
            }
        ]

        return message


    async def _send_teams_message(self, message: Dict[str, Any]) -> bool:
        """Teams 메시지 발송

        Args:
            message: Teams 메시지 페이로드

        Returns:
            발송 성공 여부
        """
        if not self.webhook_url:
            logger.warning("Teams 웹훅 URL이 설정되지 않았습니다")
            return False

        # 디버깅: 실제 사용되는 URL 로그
        logger.info(f"웹훅 URL 확인: {self.webhook_url[:100]}...")
        logger.debug(f"메시지 페이로드: {json.dumps(message, ensure_ascii=False, indent=2)}")

        for attempt in range(self.retry_count):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.webhook_url,
                        json=message,
                        headers={"Content-Type": "application/json"}
                    )

                    if response.status_code in [200, 202]:  # 202 Accepted도 성공으로 처리
                        logger.info("Teams 알림 발송 성공")
                        return True
                    else:
                        logger.warning(f"Teams 웹훅 응답 오류: {response.status_code} - {response.text}")
                        logger.debug(f"요청 URL: {self.webhook_url}")

            except httpx.RequestError as e:
                logger.warning(f"Teams 알림 발송 실패 (시도 {attempt + 1}/{self.retry_count}): {str(e)}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(2 ** attempt)  # 지수 백오프

            except Exception as e:
                logger.error(f"Teams 알림 발송 오류: {str(e)}")
                break

        return False

    async def test_notification(self) -> bool:
        """알림 테스트

        Returns:
            테스트 성공 여부
        """
        # DB 설정 로드
        await self._load_settings_from_db()

        if not self.webhook_url:
            logger.error("Teams 웹훅 URL이 설정되지 않았습니다")
            return False

        # MessageCard 형식으로 테스트 메시지 구성
        test_message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": "SSL Checker 알림 테스트",
            "themeColor": "00CC00",  # 초록색
            "title": "🧪 SSL Checker 알림 테스트",
            "text": "알림 시스템이 정상적으로 작동하고 있습니다.",
            "sections": [
                {
                    "facts": [
                        {
                            "name": "테스트 시간",
                            "value": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                        },
                        {
                            "name": "시스템 상태",
                            "value": "정상 ✅"
                        }
                    ]
                }
            ]
        }

        # Power Automate 호환성: attachments 배열 추가
        test_message["attachments"] = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.0",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "🧪 SSL Checker 알림 테스트",
                            "weight": "bolder",
                            "size": "large",
                            "color": "good"
                        },
                        {
                            "type": "TextBlock",
                            "text": "알림 시스템이 정상적으로 작동하고 있습니다.",
                            "wrap": True
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {
                                    "title": "테스트 시간",
                                    "value": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                                },
                                {
                                    "title": "시스템 상태",
                                    "value": "정상 ✅"
                                }
                            ]
                        }
                    ]
                }
            }
        ]

        return await self._send_teams_message(test_message)


# CLI 인터페이스
async def main():
    """CLI 메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="Notification Service CLI")
    subparsers = parser.add_subparsers(dest="command", help="사용 가능한 명령어")

    # 테스트 알림
    test_parser = subparsers.add_parser("test", help="알림 테스트")
    test_parser.add_argument("--webhook-url", help="Teams 웹훅 URL")

    # 만료 알림 체크
    check_parser = subparsers.add_parser("check-expiry", help="만료 알림 체크 및 발송")
    check_parser.add_argument("--webhook-url", help="Teams 웹훅 URL")
    check_parser.add_argument("--language", choices=["ko", "en"], default="ko", help="메시지 언어")

    # SSL 오류 알림
    error_parser = subparsers.add_parser("send-error", help="SSL 오류 알림 발송")
    error_parser.add_argument("website_url", help="웹사이트 URL")
    error_parser.add_argument("error_message", help="오류 메시지")
    error_parser.add_argument("--webhook-url", help="Teams 웹훅 URL")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 웹훅 URL 설정
    webhook_url = args.webhook_url or os.getenv("TEAMS_WEBHOOK_URL")
    if not webhook_url and args.command != "check-expiry":
        print("오류: Teams 웹훅 URL이 필요합니다 (--webhook-url 또는 TEAMS_WEBHOOK_URL 환경변수)")
        exit(1)

    async with db_manager.get_async_session() as session:
        service = NotificationService(
            session,
            webhook_url=webhook_url,
            language=getattr(args, "language", "ko")
        )

        try:
            if args.command == "test":
                success = await service.test_notification()
                if success:
                    print("✅ 테스트 알림이 성공적으로 발송되었습니다")
                else:
                    print("❌ 테스트 알림 발송에 실패했습니다")
                    exit(1)

            elif args.command == "check-expiry":
                success = await service.check_and_send_expiry_notifications()
                if success:
                    print("✅ 만료 알림 체크가 완료되었습니다")
                else:
                    print("❌ 만료 알림 체크에 실패했습니다")
                    exit(1)

            elif args.command == "send-error":
                # 웹사이트 조회
                from .website_manager import WebsiteManager
                manager = WebsiteManager(session)
                website = await manager.get_website_by_url(args.website_url)

                if not website:
                    print(f"오류: 웹사이트를 찾을 수 없습니다: {args.website_url}")
                    exit(1)

                success = await service.send_ssl_error_notification(website, args.error_message)
                if success:
                    print("✅ SSL 오류 알림이 성공적으로 발송되었습니다")
                else:
                    print("❌ SSL 오류 알림 발송에 실패했습니다")
                    exit(1)

        except Exception as e:
            print(f"오류: {e}")
            exit(1)


if __name__ == "__main__":
    asyncio.run(main())