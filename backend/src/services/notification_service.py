"""
알림 서비스

Teams 통합, 알림 로직을 담당하는 고수준 서비스입니다.
SSL 서비스와 연동하여 만료 알림을 자동화합니다.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.website import Website
from ..models.ssl_certificate import SSLCertificate, SSLStatus
from ..lib.notification_service import NotificationService as NotificationLib
from .ssl_service import SSLService
from ..database import get_async_session


# 로깅 설정
logger = logging.getLogger(__name__)


class NotificationServiceError(Exception):
    """알림 서비스 관련 오류"""
    pass


class NotificationService:
    """통합 알림 서비스 클래스"""

    def __init__(
        self,
        session: AsyncSession,
        webhook_url: Optional[str] = None,
        language: str = "ko",
        notification_days: List[int] = None
    ):
        """
        Args:
            session: 데이터베이스 세션
            webhook_url: Teams 웹훅 URL
            language: 메시지 언어
            notification_days: 알림 발송 일수 목록
        """
        self.session = session
        self.notification_lib = NotificationLib(session, webhook_url, language)
        self.ssl_service = SSLService(session)
        self.notification_days = notification_days or [30, 7, 1]

    async def run_scheduled_notifications(self) -> Dict[str, Any]:
        """스케줄된 알림 실행 (주간 체크와 함께)

        Returns:
            알림 실행 결과
        """
        try:
            logger.info("스케줄된 알림 실행 시작")

            # 1. 만료 임박 인증서 감지
            expiring_certificates = await self.ssl_service.detect_expiring_certificates(
                self.notification_days
            )

            # 2. 각 일수별로 알림 발송
            notification_results = []
            total_notifications_sent = 0

            for days, certs in expiring_certificates.items():
                if certs:
                    try:
                        # 일수별 알림 발송
                        success = await self._send_expiry_notifications_for_day(certs, days)
                        if success:
                            total_notifications_sent += 1

                        notification_results.append({
                            "days": days,
                            "certificate_count": len(certs),
                            "notification_sent": success
                        })

                        logger.info(f"{days}일 만료 알림 처리: {len(certs)}개 인증서")

                    except Exception as e:
                        logger.error(f"{days}일 만료 알림 발송 실패: {str(e)}")
                        notification_results.append({
                            "days": days,
                            "certificate_count": len(certs),
                            "notification_sent": False,
                            "error": str(e)
                        })

            # 3. SSL 오류 알림 체크 및 발송
            error_notifications = await self._check_and_send_ssl_error_notifications()

            result = {
                "execution_time": datetime.utcnow().isoformat(),
                "expiry_notifications": notification_results,
                "error_notifications": error_notifications,
                "total_notifications_sent": total_notifications_sent,
                "success": True
            }

            logger.info(f"스케줄된 알림 실행 완료: {total_notifications_sent}개 알림 발송")
            return result

        except Exception as e:
            logger.error(f"스케줄된 알림 실행 실패: {str(e)}")
            return {
                "execution_time": datetime.utcnow().isoformat(),
                "success": False,
                "error": str(e)
            }

    async def _send_expiry_notifications_for_day(
        self,
        certificates: List[Dict[str, Any]],
        days: int
    ) -> bool:
        """특정 일수의 만료 임박 인증서에 대한 알림 발송

        Args:
            certificates: 인증서 정보 목록
            days: 만료까지 남은 일수

        Returns:
            발송 성공 여부
        """
        try:
            # 웹사이트와 인증서 정보 추출
            website_cert_pairs = []
            for cert_info in certificates:
                website_data = cert_info["website"]
                ssl_cert_data = cert_info["ssl_certificate"]

                # Website 객체 재구성
                website = Website(
                    url=website_data["url"],
                    name=website_data["name"]
                )
                website.id = website_data["id"]

                # SSLCertificate 객체 재구성
                ssl_cert = SSLCertificate(
                    website_id=website.id,
                    issuer=ssl_cert_data["issuer"],
                    subject=ssl_cert_data["subject"],
                    serial_number=ssl_cert_data["serial_number"],
                    issued_date=datetime.fromisoformat(ssl_cert_data["issued_date"]),
                    expiry_date=datetime.fromisoformat(ssl_cert_data["expiry_date"]),
                    fingerprint=ssl_cert_data["fingerprint"],
                    status=SSLStatus(ssl_cert_data["status"])
                )

                website_cert_pairs.append((website, ssl_cert))

            # 알림 발송
            return await self.notification_lib._send_expiry_notification(
                website_cert_pairs, days
            )

        except Exception as e:
            logger.error(f"만료 알림 발송 실패 ({days}일): {str(e)}")
            return False

    async def _check_and_send_ssl_error_notifications(self) -> Dict[str, Any]:
        """SSL 오류 알림 체크 및 발송

        Returns:
            오류 알림 결과
        """
        try:
            # 최근 SSL 체크에서 오류가 발생한 웹사이트 조회
            from sqlalchemy import select, and_

            # 최근 1시간 내에 invalid 상태로 변경된 인증서 조회
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)

            result = await self.session.execute(
                select(Website, SSLCertificate)
                .join(SSLCertificate, Website.id == SSLCertificate.website_id)
                .where(
                    and_(
                        Website.is_active == True,
                        SSLCertificate.status == SSLStatus.INVALID,
                        SSLCertificate.last_checked >= one_hour_ago
                    )
                )
                .order_by(SSLCertificate.last_checked.desc())
            )

            error_cases = result.all()
            notifications_sent = 0

            for website, ssl_cert in error_cases:
                try:
                    # 이미 알림을 보냈는지 확인 (중복 방지)
                    if not await self._should_send_error_notification(website, ssl_cert):
                        continue

                    # 오류 알림 발송
                    error_message = f"SSL 인증서 검증 실패 (상태: {ssl_cert.status.value})"
                    success = await self.notification_lib.send_ssl_error_notification(
                        website, error_message
                    )

                    if success:
                        notifications_sent += 1
                        # 알림 발송 기록 (중복 방지용)
                        await self._record_error_notification_sent(website, ssl_cert)

                except Exception as e:
                    logger.error(f"SSL 오류 알림 발송 실패: {website.url} - {str(e)}")

            return {
                "error_cases_found": len(error_cases),
                "notifications_sent": notifications_sent,
                "success": True
            }

        except Exception as e:
            logger.error(f"SSL 오류 알림 체크 실패: {str(e)}")
            return {
                "error_cases_found": 0,
                "notifications_sent": 0,
                "success": False,
                "error": str(e)
            }

    async def _should_send_error_notification(
        self,
        website: Website,
        ssl_cert: SSLCertificate
    ) -> bool:
        """오류 알림을 발송해야 하는지 확인

        Args:
            website: 웹사이트 객체
            ssl_cert: SSL 인증서 객체

        Returns:
            알림 발송 여부
        """
        try:
            # 같은 웹사이트에 대해 최근 24시간 내에 오류 알림을 보냈는지 확인
            # 실제 구현에서는 별도의 notification_log 테이블을 사용할 수 있음
            # 여기서는 간단히 하루에 한 번만 보내도록 제한

            from sqlalchemy import select, and_

            twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)

            # 최근 24시간 내 같은 웹사이트의 invalid 인증서 수 확인
            result = await self.session.execute(
                select(SSLCertificate)
                .where(
                    and_(
                        SSLCertificate.website_id == website.id,
                        SSLCertificate.status == SSLStatus.INVALID,
                        SSLCertificate.last_checked >= twenty_four_hours_ago
                    )
                )
                .limit(1)
            )

            first_invalid = result.scalar_one_or_none()

            # 현재 인증서가 첫 번째 invalid 인증서인 경우에만 알림 발송
            return first_invalid and first_invalid.id == ssl_cert.id

        except Exception as e:
            logger.error(f"오류 알림 발송 여부 확인 실패: {str(e)}")
            return False

    async def _record_error_notification_sent(
        self,
        website: Website,
        ssl_cert: SSLCertificate
    ):
        """오류 알림 발송 기록

        Args:
            website: 웹사이트 객체
            ssl_cert: SSL 인증서 객체
        """
        # 실제 구현에서는 notification_log 테이블에 기록
        # 현재는 로그만 남김
        logger.info(f"오류 알림 발송 기록: {website.url} - {ssl_cert.id}")

    async def send_manual_notification(
        self,
        notification_type: str,
        target_data: Dict[str, Any]
    ) -> bool:
        """수동 알림 발송

        Args:
            notification_type: 알림 타입 ('expiry', 'error', 'test')
            target_data: 알림 대상 데이터

        Returns:
            발송 성공 여부
        """
        try:
            if notification_type == "test":
                return await self.notification_lib.test_notification()

            elif notification_type == "expiry":
                # 수동 만료 알림
                website_id = target_data.get("website_id")
                if not website_id:
                    raise NotificationServiceError("website_id가 필요합니다")

                website_info = await self._get_website_with_ssl(website_id)
                if not website_info:
                    raise NotificationServiceError("웹사이트를 찾을 수 없습니다")

                website, ssl_cert = website_info
                days_until_expiry = ssl_cert.days_until_expiry()

                return await self.notification_lib._send_expiry_notification(
                    [(website, ssl_cert)], days_until_expiry
                )

            elif notification_type == "error":
                # 수동 오류 알림
                website_id = target_data.get("website_id")
                error_message = target_data.get("error_message", "수동 오류 알림")

                if not website_id:
                    raise NotificationServiceError("website_id가 필요합니다")

                website_info = await self._get_website_with_ssl(website_id)
                if not website_info:
                    raise NotificationServiceError("웹사이트를 찾을 수 없습니다")

                website, _ = website_info
                return await self.notification_lib.send_ssl_error_notification(
                    website, error_message
                )

            else:
                raise NotificationServiceError(f"지원하지 않는 알림 타입: {notification_type}")

        except Exception as e:
            logger.error(f"수동 알림 발송 실패: {notification_type} - {str(e)}")
            raise NotificationServiceError(f"수동 알림 발송 실패: {str(e)}")

    async def _get_website_with_ssl(self, website_id: str) -> Optional[tuple]:
        """웹사이트와 최신 SSL 인증서 조회

        Args:
            website_id: 웹사이트 ID

        Returns:
            (Website, SSLCertificate) 튜플 또는 None
        """
        try:
            from sqlalchemy import select
            import uuid

            website_uuid = uuid.UUID(website_id)

            result = await self.session.execute(
                select(Website, SSLCertificate)
                .join(SSLCertificate, Website.id == SSLCertificate.website_id)
                .where(Website.id == website_uuid)
                .order_by(SSLCertificate.created_at.desc())
                .limit(1)
            )

            return result.first()

        except Exception as e:
            logger.error(f"웹사이트 SSL 정보 조회 실패: {website_id} - {str(e)}")
            return None

    async def get_notification_history(
        self,
        days: int = 7,
        notification_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """알림 히스토리 조회

        Args:
            days: 조회할 일수
            notification_type: 알림 타입 필터

        Returns:
            알림 히스토리 목록
        """
        try:
            # 실제 구현에서는 notification_log 테이블에서 조회
            # 현재는 최근 SSL 체크 기록을 기반으로 추정

            from sqlalchemy import select, and_

            since_date = datetime.utcnow() - timedelta(days=days)

            # 최근 SSL 체크 기록 조회
            result = await self.session.execute(
                select(Website, SSLCertificate)
                .join(SSLCertificate, Website.id == SSLCertificate.website_id)
                .where(
                    and_(
                        Website.is_active == True,
                        SSLCertificate.last_checked >= since_date
                    )
                )
                .order_by(SSLCertificate.last_checked.desc())
            )

            history = []
            for website, ssl_cert in result.all():
                # 만료 임박 또는 오류 상태인 경우 알림 히스토리로 간주
                should_notify = (
                    ssl_cert.is_expiring_soon(30) or
                    ssl_cert.status in [SSLStatus.INVALID, SSLStatus.EXPIRED]
                )

                if should_notify:
                    if ssl_cert.status == SSLStatus.INVALID:
                        notif_type = "error"
                        message = f"SSL 인증서 오류 (상태: {ssl_cert.status.value})"
                    else:
                        notif_type = "expiry"
                        days_left = ssl_cert.days_until_expiry()
                        message = f"SSL 인증서 만료 알림 ({days_left}일 남음)"

                    if notification_type is None or notification_type == notif_type:
                        history.append({
                            "website": website.to_dict(),
                            "ssl_certificate": ssl_cert.to_dict(),
                            "notification_type": notif_type,
                            "message": message,
                            "timestamp": ssl_cert.last_checked.isoformat(),
                            "urgency": ssl_cert.get_notification_urgency()
                        })

            logger.info(f"알림 히스토리 조회 완료: {len(history)}개 ({days}일간)")
            return history

        except Exception as e:
            logger.error(f"알림 히스토리 조회 실패: {str(e)}")
            return []

    async def get_notification_settings(self) -> Dict[str, Any]:
        """알림 설정 조회

        Returns:
            현재 알림 설정
        """
        return {
            "notification_enabled": self.notification_lib.notification_enabled,
            "webhook_url_configured": bool(self.notification_lib.webhook_url),
            "language": self.notification_lib.language,
            "notification_days": self.notification_days,
            "retry_count": self.notification_lib.retry_count,
            "timeout": self.notification_lib.timeout
        }

    async def update_notification_settings(self, settings: Dict[str, Any]) -> bool:
        """알림 설정 업데이트

        Args:
            settings: 새로운 설정

        Returns:
            업데이트 성공 여부
        """
        try:
            # webhook_url 업데이트
            if "webhook_url" in settings:
                self.notification_lib.webhook_url = settings["webhook_url"]

            # language 업데이트
            if "language" in settings:
                self.notification_lib.language = settings["language"]

            # notification_days 업데이트
            if "notification_days" in settings:
                self.notification_days = settings["notification_days"]

            # retry_count 업데이트
            if "retry_count" in settings:
                self.notification_lib.retry_count = settings["retry_count"]

            # timeout 업데이트
            if "timeout" in settings:
                self.notification_lib.timeout = settings["timeout"]

            logger.info("알림 설정 업데이트 완료")
            return True

        except Exception as e:
            logger.error(f"알림 설정 업데이트 실패: {str(e)}")
            return False


# 의존성 주입용 팩토리 함수
async def get_notification_service(
    session: AsyncSession = None,
    webhook_url: Optional[str] = None,
    language: str = "ko"
) -> NotificationService:
    """알림 서비스 팩토리 함수

    Args:
        session: 데이터베이스 세션
        webhook_url: Teams 웹훅 URL
        language: 메시지 언어

    Returns:
        알림 서비스 인스턴스
    """
    if session is None:
        async with get_async_session() as new_session:
            return NotificationService(new_session, webhook_url, language)
    else:
        return NotificationService(session, webhook_url, language)