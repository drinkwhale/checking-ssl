"""
웹사이트 서비스

웹사이트 관련 비즈니스 로직 및 SSL 체크 통합을 담당하는 서비스입니다.
"""

import asyncio
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import Depends

from ..models.website import Website
from ..models.ssl_certificate import SSLCertificate, SSLStatus
from ..lib.website_manager import WebsiteManager, WebsiteManagerError
from ..lib.ssl_checker import SSLChecker, SSLCheckError
from ..database import get_async_session


# 로깅 설정
logger = logging.getLogger(__name__)


class WebsiteServiceError(Exception):
    """웹사이트 서비스 관련 오류"""
    pass


class WebsiteService:
    """웹사이트 서비스 클래스"""

    def __init__(
        self,
        session: AsyncSession,
        ssl_timeout: int = 10,
        max_concurrent_checks: int = 5
    ):
        """
        Args:
            session: 데이터베이스 세션
            ssl_timeout: SSL 체크 타임아웃 (초)
            max_concurrent_checks: 최대 동시 SSL 체크 수
        """
        self.session = session
        self.website_manager = WebsiteManager(session)
        self.ssl_checker = SSLChecker(timeout=ssl_timeout)
        self.max_concurrent_checks = max_concurrent_checks

    async def create_website_with_ssl_check(
        self,
        url: str,
        name: Optional[str] = None,
        auto_check_ssl: bool = True
    ) -> Dict[str, Any]:
        """웹사이트 생성 및 SSL 체크 수행

        Args:
            url: 웹사이트 URL
            name: 표시명
            auto_check_ssl: 자동 SSL 체크 여부

        Returns:
            생성된 웹사이트 정보 및 SSL 체크 결과
        """
        try:
            # 웹사이트 생성
            website = await self.website_manager.create_website(url, name)

            result = {
                "website": website.to_dict(),
                "ssl_certificate": None,
                "ssl_check_error": None
            }

            # SSL 체크 수행
            if auto_check_ssl:
                ssl_result = await self._perform_ssl_check(website)
                result.update(ssl_result)

            logger.info(f"웹사이트 생성 및 SSL 체크 완료: {website.id}")
            return result

        except WebsiteManagerError as e:
            logger.error(f"웹사이트 생성 실패: {url} - {str(e)}")
            raise WebsiteServiceError(f"웹사이트 생성 실패: {str(e)}")
        except Exception as e:
            logger.error(f"웹사이트 서비스 오류: {url} - {str(e)}")
            raise WebsiteServiceError(f"웹사이트 서비스 오류: {str(e)}")

    async def _perform_ssl_check(self, website: Website) -> Dict[str, Any]:
        """웹사이트의 SSL 체크 수행

        Args:
            website: 웹사이트 객체

        Returns:
            SSL 체크 결과
        """
        try:
            # SSL 체크 수행
            ssl_result = await self.ssl_checker.check_ssl_certificate(website.url)

            # SSL 인증서 정보 저장
            ssl_certificate = await self._save_ssl_certificate_info(website, ssl_result)

            return {
                "ssl_certificate": ssl_certificate.to_dict() if ssl_certificate else None,
                "ssl_check_error": None
            }

        except SSLCheckError as e:
            # SSL 체크 실패 시 오류 상태로 저장
            error_message = str(e)
            ssl_certificate = await self._save_ssl_error(website, error_message)

            logger.warning(f"SSL 체크 실패: {website.url} - {error_message}")

            return {
                "ssl_certificate": ssl_certificate.to_dict() if ssl_certificate else None,
                "ssl_check_error": error_message
            }

    async def _save_ssl_certificate_info(
        self,
        website: Website,
        ssl_result: Dict[str, Any]
    ) -> Optional[SSLCertificate]:
        """SSL 인증서 정보를 데이터베이스에 저장

        Args:
            website: 웹사이트 객체
            ssl_result: SSL 체크 결과

        Returns:
            저장된 SSL 인증서 객체
        """
        try:
            cert_info = ssl_result["certificate"]

            # 상태 결정
            status = self._determine_ssl_status(ssl_result)

            # SSL 인증서 객체 생성
            ssl_certificate = SSLCertificate(
                website_id=website.id,
                issuer=cert_info["issuer"],
                subject=cert_info["subject"],
                serial_number=cert_info["serial_number"],
                issued_date=cert_info["not_before"],
                expiry_date=cert_info["not_after"],
                fingerprint=cert_info["fingerprint"],
                status=status
            )

            self.session.add(ssl_certificate)
            await self.session.commit()

            logger.info(f"SSL 인증서 정보 저장됨: {website.url} - {status.value}")
            return ssl_certificate

        except Exception as e:
            await self.session.rollback()
            logger.error(f"SSL 인증서 정보 저장 실패: {website.url} - {str(e)}")
            return None

    async def _save_ssl_error(
        self,
        website: Website,
        error_message: str
    ) -> Optional[SSLCertificate]:
        """SSL 오류 정보를 데이터베이스에 저장

        Args:
            website: 웹사이트 객체
            error_message: 오류 메시지

        Returns:
            저장된 SSL 인증서 객체 (오류 상태)
        """
        try:
            # 기본 정보로 SSL 인증서 레코드 생성 (오류 상태)
            ssl_certificate = SSLCertificate(
                website_id=website.id,
                issuer="Unknown (Error)",
                subject=f"CN={website.url}",
                serial_number="Error",
                issued_date=datetime.utcnow(),
                expiry_date=datetime.utcnow(),  # 임시값
                fingerprint=f"error_{website.id}_{int(datetime.utcnow().timestamp())}",
                status=SSLStatus.INVALID
            )

            self.session.add(ssl_certificate)
            await self.session.commit()

            logger.info(f"SSL 오류 정보 저장됨: {website.url} - {error_message}")
            return ssl_certificate

        except Exception as e:
            await self.session.rollback()
            logger.error(f"SSL 오류 정보 저장 실패: {website.url} - {str(e)}")
            return None

    def _determine_ssl_status(self, ssl_result: Dict[str, Any]) -> SSLStatus:
        """SSL 체크 결과로부터 상태 결정

        Args:
            ssl_result: SSL 체크 결과

        Returns:
            SSL 상태
        """
        status_str = ssl_result.get("status", "unknown").lower()

        if status_str == "valid":
            return SSLStatus.VALID
        elif status_str == "expired":
            return SSLStatus.EXPIRED
        elif status_str == "invalid":
            return SSLStatus.INVALID
        else:
            return SSLStatus.UNKNOWN

    async def update_website_with_ssl_recheck(
        self,
        website_id: uuid.UUID,
        url: Optional[str] = None,
        name: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Dict[str, Any]:
        """웹사이트 정보 업데이트 및 필요시 SSL 재체크

        Args:
            website_id: 웹사이트 ID
            url: 새 URL (변경 시 SSL 재체크)
            name: 새 이름
            is_active: 활성 상태

        Returns:
            업데이트된 웹사이트 정보
        """
        try:
            # 기존 웹사이트 정보 조회
            original_website = await self.website_manager.get_website_by_id(website_id)
            if not original_website:
                raise WebsiteServiceError(f"웹사이트를 찾을 수 없습니다: {website_id}")

            original_url = original_website.url

            # 웹사이트 정보 업데이트
            updated_website = await self.website_manager.update_website(
                website_id, url, name, is_active
            )

            result = {
                "website": updated_website.to_dict(),
                "ssl_certificate": None,
                "ssl_check_error": None,
                "ssl_rechecked": False
            }

            # URL이 변경된 경우 SSL 재체크
            if url and url != original_url:
                ssl_result = await self._perform_ssl_check(updated_website)
                result.update(ssl_result)
                result["ssl_rechecked"] = True

            logger.info(f"웹사이트 업데이트 완료: {website_id}")
            return result

        except WebsiteManagerError as e:
            raise WebsiteServiceError(f"웹사이트 업데이트 실패: {str(e)}")

    async def get_website_with_latest_ssl(self, website_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """웹사이트와 최신 SSL 인증서 정보 조회

        Args:
            website_id: 웹사이트 ID

        Returns:
            웹사이트 및 SSL 정보
        """
        try:
            website = await self.website_manager.get_website_by_id(website_id)
            if not website:
                return None

            # 최신 SSL 인증서 조회
            from sqlalchemy import select
            result = await self.session.execute(
                select(SSLCertificate)
                .where(SSLCertificate.website_id == website_id)
                .order_by(SSLCertificate.created_at.desc())
                .limit(1)
            )
            latest_ssl = result.scalar_one_or_none()

            return {
                "website": website.to_dict(),
                "ssl_certificate": latest_ssl.to_dict() if latest_ssl else None
            }

        except Exception as e:
            logger.error(f"웹사이트 SSL 정보 조회 실패: {website_id} - {str(e)}")
            return None

    async def manual_ssl_check(self, website_id: uuid.UUID) -> Dict[str, Any]:
        """수동 SSL 체크 수행

        Args:
            website_id: 웹사이트 ID

        Returns:
            SSL 체크 결과
        """
        try:
            website = await self.website_manager.get_website_by_id(website_id)
            if not website:
                raise WebsiteServiceError(f"웹사이트를 찾을 수 없습니다: {website_id}")

            # SSL 체크 수행
            ssl_result = await self._perform_ssl_check(website)

            result = {
                "website": website.to_dict(),
                "manual_check": True,
                "checked_at": datetime.utcnow().isoformat()
            }
            result.update(ssl_result)

            logger.info(f"수동 SSL 체크 완료: {website.url}")
            return result

        except Exception as e:
            logger.error(f"수동 SSL 체크 실패: {website_id} - {str(e)}")
            raise WebsiteServiceError(f"수동 SSL 체크 실패: {str(e)}")

    async def batch_ssl_check(
        self,
        website_ids: Optional[List[uuid.UUID]] = None,
        active_only: bool = True
    ) -> Dict[str, Any]:
        """일괄 SSL 체크 수행

        Args:
            website_ids: 체크할 웹사이트 ID 목록 (None이면 전체)
            active_only: 활성 웹사이트만 체크

        Returns:
            일괄 체크 결과
        """
        try:
            # 대상 웹사이트 조회
            if website_ids:
                websites = []
                for website_id in website_ids:
                    website = await self.website_manager.get_website_by_id(website_id)
                    if website and (not active_only or website.is_active):
                        websites.append(website)
            else:
                websites = await self.website_manager.get_all_websites(active_only=active_only)

            if not websites:
                return {
                    "total_websites": 0,
                    "successful_checks": 0,
                    "failed_checks": 0,
                    "results": []
                }

            # 동시 SSL 체크 수행
            semaphore = asyncio.Semaphore(self.max_concurrent_checks)

            async def check_website_ssl(website: Website) -> Dict[str, Any]:
                async with semaphore:
                    try:
                        ssl_result = await self._perform_ssl_check(website)
                        return {
                            "website_id": str(website.id),
                            "url": website.url,
                            "success": True,
                            "ssl_certificate": ssl_result.get("ssl_certificate"),
                            "error": ssl_result.get("ssl_check_error")
                        }
                    except Exception as e:
                        logger.error(f"웹사이트 SSL 체크 실패: {website.url} - {str(e)}")
                        return {
                            "website_id": str(website.id),
                            "url": website.url,
                            "success": False,
                            "error": str(e)
                        }

            # 모든 웹사이트에 대해 SSL 체크 수행
            tasks = [check_website_ssl(website) for website in websites]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 결과 집계
            successful_checks = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
            failed_checks = len(results) - successful_checks

            batch_result = {
                "total_websites": len(websites),
                "successful_checks": successful_checks,
                "failed_checks": failed_checks,
                "results": [r for r in results if isinstance(r, dict)],
                "checked_at": datetime.utcnow().isoformat()
            }

            logger.info(f"일괄 SSL 체크 완료: {successful_checks}/{len(websites)} 성공")
            return batch_result

        except Exception as e:
            logger.error(f"일괄 SSL 체크 실패: {str(e)}")
            raise WebsiteServiceError(f"일괄 SSL 체크 실패: {str(e)}")

    async def get_expiring_certificates(self, days: int = 30) -> List[Dict[str, Any]]:
        """만료 임박 인증서 조회

        Args:
            days: 만료 임박 기준 일수

        Returns:
            만료 임박 인증서 목록
        """
        try:
            from sqlalchemy import select, and_
            from datetime import timedelta

            target_date = datetime.utcnow() + timedelta(days=days)

            result = await self.session.execute(
                select(Website, SSLCertificate)
                .join(SSLCertificate, Website.id == SSLCertificate.website_id)
                .where(
                    and_(
                        Website.is_active == True,
                        SSLCertificate.expiry_date <= target_date,
                        SSLCertificate.expiry_date > datetime.utcnow(),
                        SSLCertificate.status == SSLStatus.VALID
                    )
                )
                .order_by(SSLCertificate.expiry_date)
            )

            expiring_certs = []
            for website, cert in result.all():
                expiring_certs.append({
                    "website": website.to_dict(),
                    "ssl_certificate": cert.to_dict(),
                    "days_until_expiry": cert.days_until_expiry()
                })

            logger.info(f"만료 임박 인증서 조회 완료: {len(expiring_certs)}개 ({days}일 기준)")
            return expiring_certs

        except Exception as e:
            logger.error(f"만료 임박 인증서 조회 실패: {str(e)}")
            return []

    async def get_ssl_statistics(self) -> Dict[str, Any]:
        """SSL 인증서 통계 조회

        Returns:
            SSL 통계 정보
        """
        try:
            from sqlalchemy import select, func
            from datetime import timedelta

            # 전체 통계
            total_websites = len(await self.website_manager.get_all_websites())
            active_websites = len(await self.website_manager.get_all_websites(active_only=True))

            # SSL 상태별 통계
            status_result = await self.session.execute(
                select(SSLCertificate.status, func.count(SSLCertificate.id))
                .group_by(SSLCertificate.status)
            )

            status_stats = {}
            for status, count in status_result.all():
                status_stats[status.value] = count

            # 만료 임박 통계
            now = datetime.utcnow()
            expiry_stats = {}
            for days in [1, 7, 30]:
                target_date = now + timedelta(days=days)
                expiry_result = await self.session.execute(
                    select(func.count(SSLCertificate.id))
                    .join(Website, Website.id == SSLCertificate.website_id)
                    .where(
                        and_(
                            Website.is_active == True,
                            SSLCertificate.expiry_date <= target_date,
                            SSLCertificate.expiry_date > now,
                            SSLCertificate.status == SSLStatus.VALID
                        )
                    )
                )
                expiry_stats[f"expiring_in_{days}_days"] = expiry_result.scalar() or 0

            return {
                "total_websites": total_websites,
                "active_websites": active_websites,
                "ssl_status_distribution": status_stats,
                "expiry_statistics": expiry_stats,
                "generated_at": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"SSL 통계 조회 실패: {str(e)}")
            return {}

    async def delete_website_with_cleanup(self, website_id: uuid.UUID) -> bool:
        """웹사이트 삭제 및 관련 데이터 정리

        Args:
            website_id: 웹사이트 ID

        Returns:
            삭제 성공 여부
        """
        try:
            # 웹사이트 삭제 (CASCADE로 SSL 인증서도 함께 삭제됨)
            success = await self.website_manager.delete_website(website_id)

            if success:
                logger.info(f"웹사이트 삭제 및 정리 완료: {website_id}")

            return success

        except Exception as e:
            logger.error(f"웹사이트 삭제 실패: {website_id} - {str(e)}")
            raise WebsiteServiceError(f"웹사이트 삭제 실패: {str(e)}")


# 의존성 주입용 팩토리 함수
async def get_website_service(session: AsyncSession = Depends(get_async_session)) -> WebsiteService:
    """웹사이트 서비스 팩토리 함수 (FastAPI Depends용)

    Args:
        session: 데이터베이스 세션 (FastAPI dependency injection)

    Returns:
        웹사이트 서비스 인스턴스
    """
    return WebsiteService(session)