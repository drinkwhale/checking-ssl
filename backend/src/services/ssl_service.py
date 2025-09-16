"""
SSL 모니터링 서비스

SSL 인증서 일괄 체크, 만료 감지, 모니터링을 담당하는 서비스입니다.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, update

from ..models.website import Website
from ..models.ssl_certificate import SSLCertificate, SSLStatus
from ..lib.ssl_checker import SSLChecker, SSLCheckError
from ..lib.website_manager import WebsiteManager
from ..database import get_async_session


# 로깅 설정
logger = logging.getLogger(__name__)


class SSLServiceError(Exception):
    """SSL 서비스 관련 오류"""
    pass


class SSLService:
    """SSL 모니터링 서비스 클래스"""

    def __init__(
        self,
        session: AsyncSession,
        ssl_timeout: int = 10,
        max_concurrent_checks: int = 5,
        retry_failed_checks: bool = True
    ):
        """
        Args:
            session: 데이터베이스 세션
            ssl_timeout: SSL 체크 타임아웃 (초)
            max_concurrent_checks: 최대 동시 체크 수
            retry_failed_checks: 실패한 체크 재시도 여부
        """
        self.session = session
        self.ssl_checker = SSLChecker(timeout=ssl_timeout)
        self.website_manager = WebsiteManager(session)
        self.max_concurrent_checks = max_concurrent_checks
        self.retry_failed_checks = retry_failed_checks

    async def check_all_websites_ssl(self, active_only: bool = True) -> Dict[str, Any]:
        """모든 웹사이트의 SSL 인증서 일괄 체크

        Args:
            active_only: 활성 웹사이트만 체크

        Returns:
            일괄 체크 결과
        """
        start_time = datetime.utcnow()

        try:
            # 대상 웹사이트 조회
            websites = await self.website_manager.get_all_websites(active_only=active_only)

            if not websites:
                return {
                    "total_processed": 0,
                    "successful_checks": 0,
                    "failed_checks": 0,
                    "processing_time_seconds": 0,
                    "results": []
                }

            logger.info(f"SSL 일괄 체크 시작: {len(websites)}개 웹사이트")

            # 동시 SSL 체크 수행
            results = await self._perform_concurrent_ssl_checks(websites)

            # 결과 처리 및 통계 생성
            end_time = datetime.utcnow()
            processing_time = (end_time - start_time).total_seconds()

            successful_checks = sum(1 for r in results if r.get("success", False))
            failed_checks = len(results) - successful_checks

            batch_result = {
                "total_processed": len(websites),
                "successful_checks": successful_checks,
                "failed_checks": failed_checks,
                "processing_time_seconds": processing_time,
                "average_check_time": processing_time / len(websites) if websites else 0,
                "active_websites_only": active_only,
                "checked_at": end_time.isoformat(),
                "results": results
            }

            logger.info(
                f"SSL 일괄 체크 완료: {successful_checks}/{len(websites)} 성공, "
                f"소요시간: {processing_time:.2f}초"
            )

            return batch_result

        except Exception as e:
            logger.error(f"SSL 일괄 체크 실패: {str(e)}")
            raise SSLServiceError(f"SSL 일괄 체크 실패: {str(e)}")

    async def _perform_concurrent_ssl_checks(self, websites: List[Website]) -> List[Dict[str, Any]]:
        """동시 SSL 체크 수행

        Args:
            websites: 체크할 웹사이트 목록

        Returns:
            체크 결과 목록
        """
        semaphore = asyncio.Semaphore(self.max_concurrent_checks)

        async def check_single_website(website: Website) -> Dict[str, Any]:
            async with semaphore:
                return await self._check_website_ssl_with_retry(website)

        # 모든 웹사이트에 대해 동시 체크 수행
        tasks = [check_single_website(website) for website in websites]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 예외 처리된 결과 반환
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "website_id": str(websites[i].id),
                    "url": websites[i].url,
                    "success": False,
                    "error": str(result),
                    "checked_at": datetime.utcnow().isoformat()
                })
            else:
                processed_results.append(result)

        return processed_results

    async def _check_website_ssl_with_retry(self, website: Website) -> Dict[str, Any]:
        """재시도 포함 웹사이트 SSL 체크

        Args:
            website: 체크할 웹사이트

        Returns:
            체크 결과
        """
        max_retries = 2 if self.retry_failed_checks else 1
        last_error = None

        for attempt in range(max_retries):
            try:
                # SSL 체크 수행
                ssl_result = await self.ssl_checker.check_ssl_certificate(website.url)

                # 성공 시 데이터베이스에 저장
                ssl_certificate = await self._save_ssl_certificate_result(website, ssl_result)

                return {
                    "website_id": str(website.id),
                    "url": website.url,
                    "success": True,
                    "ssl_certificate": ssl_certificate.to_dict() if ssl_certificate else None,
                    "attempt": attempt + 1,
                    "checked_at": datetime.utcnow().isoformat()
                }

            except SSLCheckError as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    logger.warning(f"SSL 체크 실패, 재시도: {website.url} (시도 {attempt + 1})")
                    await asyncio.sleep(1)  # 1초 대기 후 재시도
                else:
                    # 모든 재시도 실패 시 오류 상태로 저장
                    await self._save_ssl_error_result(website, last_error)

        return {
            "website_id": str(website.id),
            "url": website.url,
            "success": False,
            "error": last_error,
            "attempts": max_retries,
            "checked_at": datetime.utcnow().isoformat()
        }

    async def _save_ssl_certificate_result(
        self,
        website: Website,
        ssl_result: Dict[str, Any]
    ) -> Optional[SSLCertificate]:
        """SSL 체크 결과를 데이터베이스에 저장

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

            # 기존 인증서와 중복 확인 (fingerprint 기준)
            fingerprint = cert_info["fingerprint"]
            existing_cert = await self._find_existing_certificate(website.id, fingerprint)

            if existing_cert:
                # 기존 인증서 업데이트
                existing_cert.last_checked = datetime.utcnow()
                existing_cert.status = status
                await self.session.commit()
                return existing_cert
            else:
                # 새 인증서 생성
                ssl_certificate = SSLCertificate(
                    website_id=website.id,
                    issuer=cert_info["issuer"],
                    subject=cert_info["subject"],
                    serial_number=cert_info["serial_number"],
                    issued_date=cert_info["not_before"],
                    expiry_date=cert_info["not_after"],
                    fingerprint=fingerprint,
                    status=status
                )

                self.session.add(ssl_certificate)
                await self.session.commit()
                await self.session.refresh(ssl_certificate)

                logger.debug(f"새 SSL 인증서 저장됨: {website.url}")
                return ssl_certificate

        except Exception as e:
            await self.session.rollback()
            logger.error(f"SSL 인증서 결과 저장 실패: {website.url} - {str(e)}")
            return None

    async def _save_ssl_error_result(self, website: Website, error_message: str):
        """SSL 오류 결과를 데이터베이스에 저장

        Args:
            website: 웹사이트 객체
            error_message: 오류 메시지
        """
        try:
            # 기존 오류 인증서가 있는지 확인
            error_fingerprint = f"error_{website.id}_{int(datetime.utcnow().timestamp())}"

            ssl_certificate = SSLCertificate(
                website_id=website.id,
                issuer="Error",
                subject=f"CN={website.url}",
                serial_number="Error",
                issued_date=datetime.utcnow(),
                expiry_date=datetime.utcnow(),
                fingerprint=error_fingerprint,
                status=SSLStatus.INVALID
            )

            self.session.add(ssl_certificate)
            await self.session.commit()

            logger.debug(f"SSL 오류 결과 저장됨: {website.url} - {error_message}")

        except Exception as e:
            await self.session.rollback()
            logger.error(f"SSL 오류 결과 저장 실패: {website.url} - {str(e)}")

    async def _find_existing_certificate(
        self,
        website_id: uuid.UUID,
        fingerprint: str
    ) -> Optional[SSLCertificate]:
        """기존 인증서 찾기

        Args:
            website_id: 웹사이트 ID
            fingerprint: 인증서 지문

        Returns:
            기존 인증서 또는 None
        """
        try:
            result = await self.session.execute(
                select(SSLCertificate).where(
                    and_(
                        SSLCertificate.website_id == website_id,
                        SSLCertificate.fingerprint == fingerprint
                    )
                )
            )
            return result.scalar_one_or_none()
        except Exception:
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

    async def detect_expiring_certificates(self, days_list: List[int] = None) -> Dict[int, List[Dict]]:
        """만료 임박 인증서 감지

        Args:
            days_list: 체크할 일수 목록 (기본: [30, 7, 1])

        Returns:
            일수별 만료 임박 인증서 딕셔너리
        """
        if days_list is None:
            days_list = [30, 7, 1]

        try:
            expiring_by_days = {}

            for days in days_list:
                target_date = datetime.utcnow() + timedelta(days=days)
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

                expiring_certs = []
                for website, cert in result.all():
                    expiring_certs.append({
                        "website": website.to_dict(),
                        "ssl_certificate": cert.to_dict(),
                        "days_until_expiry": cert.days_until_expiry(),
                        "urgency": cert.get_notification_urgency()
                    })

                expiring_by_days[days] = expiring_certs

                logger.info(f"만료 임박 인증서 감지 ({days}일): {len(expiring_certs)}개")

            return expiring_by_days

        except Exception as e:
            logger.error(f"만료 임박 인증서 감지 실패: {str(e)}")
            return {}

    async def get_ssl_health_status(self) -> Dict[str, Any]:
        """SSL 헬스 상태 조회

        Returns:
            SSL 헬스 상태 정보
        """
        try:
            # 전체 통계
            total_websites = len(await self.website_manager.get_all_websites())
            active_websites = len(await self.website_manager.get_all_websites(active_only=True))

            # 최근 24시간 내 체크된 인증서 수
            yesterday = datetime.utcnow() - timedelta(days=1)
            recent_checks_result = await self.session.execute(
                select(func.count(SSLCertificate.id))
                .where(SSLCertificate.last_checked >= yesterday)
            )
            recent_checks = recent_checks_result.scalar() or 0

            # 상태별 분포
            status_result = await self.session.execute(
                select(SSLCertificate.status, func.count(SSLCertificate.id))
                .join(Website, Website.id == SSLCertificate.website_id)
                .where(Website.is_active == True)
                .group_by(SSLCertificate.status)
            )

            status_distribution = {}
            for status, count in status_result.all():
                status_distribution[status.value] = count

            # 만료 임박 통계
            expiring_stats = await self._get_expiring_statistics()

            # 헬스 스코어 계산
            health_score = self._calculate_health_score(
                status_distribution,
                expiring_stats,
                active_websites
            )

            return {
                "overall_health": health_score,
                "total_websites": total_websites,
                "active_websites": active_websites,
                "recent_checks_24h": recent_checks,
                "status_distribution": status_distribution,
                "expiring_statistics": expiring_stats,
                "last_updated": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"SSL 헬스 상태 조회 실패: {str(e)}")
            return {"overall_health": "error", "error": str(e)}

    async def _get_expiring_statistics(self) -> Dict[str, int]:
        """만료 임박 통계 조회

        Returns:
            만료 임박 통계
        """
        expiring_stats = {}
        now = datetime.utcnow()

        for days in [1, 7, 30]:
            target_date = now + timedelta(days=days)
            result = await self.session.execute(
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
            expiring_stats[f"expiring_in_{days}_days"] = result.scalar() or 0

        return expiring_stats

    def _calculate_health_score(
        self,
        status_distribution: Dict[str, int],
        expiring_stats: Dict[str, int],
        total_active: int
    ) -> str:
        """헬스 스코어 계산

        Args:
            status_distribution: 상태별 분포
            expiring_stats: 만료 임박 통계
            total_active: 전체 활성 웹사이트 수

        Returns:
            헬스 스코어 ('excellent', 'good', 'warning', 'critical')
        """
        if total_active == 0:
            return "unknown"

        # 유효한 인증서 비율
        valid_count = status_distribution.get("valid", 0)
        valid_ratio = valid_count / total_active if total_active > 0 else 0

        # 만료 임박 인증서 비율
        critical_expiring = expiring_stats.get("expiring_in_1_days", 0)
        warning_expiring = expiring_stats.get("expiring_in_7_days", 0)

        critical_ratio = critical_expiring / total_active if total_active > 0 else 0
        warning_ratio = warning_expiring / total_active if total_active > 0 else 0

        # 스코어 계산
        if critical_ratio > 0.1 or valid_ratio < 0.7:  # 10% 이상 긴급 만료 또는 70% 미만 유효
            return "critical"
        elif warning_ratio > 0.2 or valid_ratio < 0.85:  # 20% 이상 경고 만료 또는 85% 미만 유효
            return "warning"
        elif valid_ratio >= 0.95:  # 95% 이상 유효
            return "excellent"
        else:
            return "good"

    async def cleanup_old_certificates(self, keep_days: int = 90) -> int:
        """오래된 SSL 인증서 레코드 정리

        Args:
            keep_days: 보관할 일수

        Returns:
            삭제된 레코드 수
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=keep_days)

            # 각 웹사이트별로 최신 인증서는 보존하고 오래된 것만 삭제
            subquery = (
                select(
                    SSLCertificate.website_id,
                    func.max(SSLCertificate.created_at).label("latest_created_at")
                )
                .group_by(SSLCertificate.website_id)
                .subquery()
            )

            # 오래된 인증서 중에서 최신이 아닌 것들만 삭제
            delete_result = await self.session.execute(
                select(SSLCertificate.id)
                .join(
                    subquery,
                    and_(
                        SSLCertificate.website_id == subquery.c.website_id,
                        SSLCertificate.created_at < subquery.c.latest_created_at
                    )
                )
                .where(SSLCertificate.created_at < cutoff_date)
            )

            old_cert_ids = [row[0] for row in delete_result.all()]

            if old_cert_ids:
                # 실제 삭제 수행
                from sqlalchemy import delete
                await self.session.execute(
                    delete(SSLCertificate).where(SSLCertificate.id.in_(old_cert_ids))
                )
                await self.session.commit()

                logger.info(f"오래된 SSL 인증서 정리 완료: {len(old_cert_ids)}개 삭제")
                return len(old_cert_ids)
            else:
                logger.info("정리할 오래된 SSL 인증서가 없습니다")
                return 0

        except Exception as e:
            await self.session.rollback()
            logger.error(f"SSL 인증서 정리 실패: {str(e)}")
            raise SSLServiceError(f"SSL 인증서 정리 실패: {str(e)}")

    async def force_refresh_website_ssl(self, website_id: uuid.UUID) -> Dict[str, Any]:
        """웹사이트 SSL 강제 새로고침

        Args:
            website_id: 웹사이트 ID

        Returns:
            새로고침 결과
        """
        try:
            website = await self.website_manager.get_website_by_id(website_id)
            if not website:
                raise SSLServiceError(f"웹사이트를 찾을 수 없습니다: {website_id}")

            # SSL 체크 수행
            result = await self._check_website_ssl_with_retry(website)

            logger.info(f"SSL 강제 새로고침 완료: {website.url}")
            return result

        except Exception as e:
            logger.error(f"SSL 강제 새로고침 실패: {website_id} - {str(e)}")
            raise SSLServiceError(f"SSL 강제 새로고침 실패: {str(e)}")


# 의존성 주입용 팩토리 함수
async def get_ssl_service(session: AsyncSession = None) -> SSLService:
    """SSL 서비스 팩토리 함수

    Args:
        session: 데이터베이스 세션 (None이면 새로 생성)

    Returns:
        SSL 서비스 인스턴스
    """
    if session is None:
        async with get_async_session() as new_session:
            return SSLService(new_session)
    else:
        return SSLService(session)