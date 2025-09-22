"""
SSL 모니터링 API 엔드포인트

SSL 인증서 상태 조회, 수동 체크, 히스토리 등의 SSL 관련 API를 제공합니다.
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from ..database import get_async_session
from ..models.website import Website
from ..models.ssl_certificate import SSLCertificate, SSLStatus
from ..services.ssl_service import get_ssl_service, SSLService, SSLServiceError


# APIRouter 생성
router = APIRouter(prefix="/api/ssl", tags=["ssl"])


# Request/Response 모델 정의
class SSLCheckRequest(BaseModel):
    """SSL 체크 요청"""
    url: HttpUrl = Field(..., description="체크할 URL")
    timeout: Optional[int] = Field(10, ge=1, le=60, description="타임아웃 (초)")


class SSLCertificateInfo(BaseModel):
    """SSL 인증서 정보"""
    website_id: str = Field(..., description="웹사이트 ID")
    website_url: str = Field(..., description="웹사이트 URL")
    website_name: Optional[str] = Field(None, description="웹사이트 표시명")

    certificate_id: str = Field(..., description="인증서 ID")
    issuer: str = Field(..., description="발행기관")
    subject: str = Field(..., description="주체")
    serial_number: str = Field(..., description="시리얼 번호")
    issued_date: datetime = Field(..., description="발행일")
    expiry_date: datetime = Field(..., description="만료일")
    fingerprint: str = Field(..., description="지문")
    status: str = Field(..., description="상태")

    days_until_expiry: int = Field(..., description="만료까지 남은 일수")
    is_expired: bool = Field(..., description="만료 여부")
    created_at: datetime = Field(..., description="등록일")
    updated_at: datetime = Field(..., description="수정일")


class SSLStatusSummary(BaseModel):
    """SSL 상태 요약"""
    total_websites: int = Field(..., description="전체 웹사이트 수")
    total_certificates: int = Field(..., description="전체 인증서 수")
    valid_certificates: int = Field(..., description="유효한 인증서 수")
    expired_certificates: int = Field(..., description="만료된 인증서 수")
    invalid_certificates: int = Field(..., description="무효한 인증서 수")
    unknown_certificates: int = Field(..., description="상태 불명 인증서 수")

    expiring_in_7_days: int = Field(..., description="7일 내 만료 예정")
    expiring_in_30_days: int = Field(..., description="30일 내 만료 예정")

    last_check_time: Optional[datetime] = Field(None, description="최종 체크 시간")


class SSLHistoryEntry(BaseModel):
    """SSL 히스토리 항목"""
    check_date: datetime = Field(..., description="체크 날짜")
    status: str = Field(..., description="상태")
    issuer: str = Field(..., description="발행기관")
    expiry_date: datetime = Field(..., description="만료일")
    days_until_expiry: int = Field(..., description="만료까지 남은 일수")
    error_message: Optional[str] = Field(None, description="오류 메시지")


class QuickCheckResponse(BaseModel):
    """빠른 체크 응답"""
    url: str = Field(..., description="체크한 URL")
    is_valid: bool = Field(..., description="유효 여부")
    status: str = Field(..., description="상태")
    certificate_info: Optional[Dict[str, Any]] = Field(None, description="인증서 정보")
    error_message: Optional[str] = Field(None, description="오류 메시지")
    check_duration_ms: int = Field(..., description="체크 소요 시간 (밀리초)")
    checked_at: datetime = Field(..., description="체크 시간")


# SSL 상태 조회 엔드포인트

@router.get("/status", response_model=SSLStatusSummary)
async def get_ssl_status_summary(
    active_only: bool = Query(True, description="활성 웹사이트만 포함"),
    session: AsyncSession = Depends(get_async_session)
) -> SSLStatusSummary:
    """
    SSL 상태 요약 정보 조회

    등록된 모든 SSL 인증서의 상태 요약 정보를 제공합니다.
    """
    try:
        # 기본 필터 조건 설정
        filters = []
        if active_only:
            filters.append(Website.is_active == True)

        # 전체 웹사이트 수 조회
        website_count_query = select(Website.id)
        if filters:
            website_count_query = website_count_query.where(and_(*filters))

        website_result = await session.execute(website_count_query)
        total_websites = len(website_result.all())

        # 전체 인증서 수 조회
        count_query = select(SSLCertificate.id).join(Website, Website.id == SSLCertificate.website_id)
        if filters:
            count_query = count_query.where(and_(*filters))

        total_result = await session.execute(count_query)
        total_certificates = len(total_result.all())

        # 상태별 집계
        status_query = select(SSLCertificate.status).join(Website, Website.id == SSLCertificate.website_id)
        if filters:
            status_query = status_query.where(and_(*filters))

        status_result = await session.execute(status_query)

        status_counts = {status.value: 0 for status in SSLStatus}
        for status, in status_result.all():
            status_counts[status.value] = status_counts.get(status.value, 0) + 1

        # 만료 임박 통계
        now = datetime.utcnow()
        seven_days_later = now + timedelta(days=7)
        thirty_days_later = now + timedelta(days=30)

        # 7일 내 만료 예정
        expiring_7_query = select(SSLCertificate.id).join(Website, Website.id == SSLCertificate.website_id)
        expiring_7_filters = filters + [
            SSLCertificate.expiry_date <= seven_days_later,
            SSLCertificate.expiry_date > now,
            SSLCertificate.status == SSLStatus.VALID
        ]
        if expiring_7_filters:
            expiring_7_query = expiring_7_query.where(and_(*expiring_7_filters))

        expiring_7_result = await session.execute(expiring_7_query)
        expiring_in_7_days = len(expiring_7_result.all())

        # 30일 내 만료 예정
        expiring_30_query = select(SSLCertificate.id).join(Website, Website.id == SSLCertificate.website_id)
        expiring_30_filters = filters + [
            SSLCertificate.expiry_date <= thirty_days_later,
            SSLCertificate.expiry_date > now,
            SSLCertificate.status == SSLStatus.VALID
        ]
        if expiring_30_filters:
            expiring_30_query = expiring_30_query.where(and_(*expiring_30_filters))

        expiring_30_result = await session.execute(expiring_30_query)
        expiring_in_30_days = len(expiring_30_result.all())

        # 최근 체크 시간
        latest_check_query = select(SSLCertificate.created_at).join(Website, Website.id == SSLCertificate.website_id)
        if filters:
            latest_check_query = latest_check_query.where(and_(*filters))
        latest_check_query = latest_check_query.order_by(desc(SSLCertificate.created_at)).limit(1)

        latest_check_result = await session.execute(latest_check_query)
        last_check_time = latest_check_result.scalar_one_or_none()

        return SSLStatusSummary(
            total_websites=total_websites,
            total_certificates=total_certificates,
            valid_certificates=status_counts.get("valid", 0),
            expired_certificates=status_counts.get("expired", 0),
            invalid_certificates=status_counts.get("invalid", 0),
            unknown_certificates=status_counts.get("unknown", 0),
            expiring_in_7_days=expiring_in_7_days,
            expiring_in_30_days=expiring_in_30_days,
            last_check_time=last_check_time
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 상태 요약 조회 중 오류가 발생했습니다"
        )


@router.get("/certificates", response_model=List[SSLCertificateInfo])
async def get_ssl_certificates(
    active_only: bool = Query(True, description="활성 웹사이트만 포함"),
    status_filter: Optional[str] = Query(None, description="상태 필터 (valid, expired, invalid, unknown)"),
    expiring_within_days: Optional[int] = Query(None, ge=1, le=365, description="지정 일수 내 만료 예정만 포함"),
    limit: int = Query(100, ge=1, le=1000, description="결과 수 제한"),
    offset: int = Query(0, ge=0, description="결과 오프셋"),
    session: AsyncSession = Depends(get_async_session)
) -> List[SSLCertificateInfo]:
    """
    SSL 인증서 목록 조회

    다양한 필터 조건으로 SSL 인증서 목록을 조회합니다.
    """
    try:
        # 기본 쿼리 구성
        query = select(SSLCertificate, Website).join(
            Website, Website.id == SSLCertificate.website_id
        )

        # 필터 적용
        filters = []

        if active_only:
            filters.append(Website.is_active == True)

        if status_filter:
            try:
                ssl_status = SSLStatus(status_filter.lower())
                filters.append(SSLCertificate.status == ssl_status)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"유효하지 않은 상태 값입니다: {status_filter}"
                )

        if expiring_within_days:
            target_date = datetime.utcnow() + timedelta(days=expiring_within_days)
            filters.append(
                and_(
                    SSLCertificate.expiry_date <= target_date,
                    SSLCertificate.expiry_date > datetime.utcnow(),
                    SSLCertificate.status == SSLStatus.VALID
                )
            )

        if filters:
            query = query.where(and_(*filters))

        # 정렬 및 페이징
        query = query.order_by(desc(SSLCertificate.created_at)).offset(offset).limit(limit)

        # 실행
        result = await session.execute(query)
        records = result.all()

        # 응답 구성
        certificates = []
        for cert, website in records:
            certificates.append(SSLCertificateInfo(
                website_id=str(website.id),
                website_url=website.url,
                website_name=website.name,
                certificate_id=str(cert.id),
                issuer=cert.issuer,
                subject=cert.subject,
                serial_number=cert.serial_number,
                issued_date=cert.issued_date,
                expiry_date=cert.expiry_date,
                fingerprint=cert.fingerprint,
                status=cert.status.value,
                days_until_expiry=cert.days_until_expiry(),
                is_expired=cert.is_expired(),
                created_at=cert.created_at,
                updated_at=cert.updated_at
            ))

        return certificates

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 인증서 목록 조회 중 오류가 발생했습니다"
        )


@router.get("/certificates/{certificate_id}", response_model=SSLCertificateInfo)
async def get_ssl_certificate(
    certificate_id: str,
    session: AsyncSession = Depends(get_async_session)
) -> SSLCertificateInfo:
    """
    특정 SSL 인증서 조회

    인증서 ID로 특정 SSL 인증서의 세부 정보를 조회합니다.
    """
    try:
        # UUID 변환
        try:
            uuid_id = uuid.UUID(certificate_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효하지 않은 인증서 ID 형식입니다"
            )

        # 인증서 조회
        result = await session.execute(
            select(SSLCertificate, Website)
            .join(Website, Website.id == SSLCertificate.website_id)
            .where(SSLCertificate.id == uuid_id)
        )
        record = result.first()

        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="SSL 인증서를 찾을 수 없습니다"
            )

        cert, website = record

        return SSLCertificateInfo(
            website_id=str(website.id),
            website_url=website.url,
            website_name=website.name,
            certificate_id=str(cert.id),
            issuer=cert.issuer,
            subject=cert.subject,
            serial_number=cert.serial_number,
            issued_date=cert.issued_date,
            expiry_date=cert.expiry_date,
            fingerprint=cert.fingerprint,
            status=cert.status.value,
            days_until_expiry=cert.days_until_expiry(),
            is_expired=cert.is_expired(),
            created_at=cert.created_at,
            updated_at=cert.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 인증서 조회 중 오류가 발생했습니다"
        )


@router.get("/history/{website_id}", response_model=List[SSLHistoryEntry])
async def get_ssl_history(
    website_id: str,
    days: int = Query(30, ge=1, le=365, description="히스토리 조회 일수"),
    limit: int = Query(50, ge=1, le=500, description="결과 수 제한"),
    session: AsyncSession = Depends(get_async_session)
) -> List[SSLHistoryEntry]:
    """
    웹사이트별 SSL 히스토리 조회

    특정 웹사이트의 SSL 인증서 변경 이력을 조회합니다.
    """
    try:
        # UUID 변환
        try:
            uuid_id = uuid.UUID(website_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효하지 않은 웹사이트 ID 형식입니다"
            )

        # 날짜 범위 설정
        start_date = datetime.utcnow() - timedelta(days=days)

        # 히스토리 조회
        result = await session.execute(
            select(SSLCertificate)
            .where(
                and_(
                    SSLCertificate.website_id == uuid_id,
                    SSLCertificate.created_at >= start_date
                )
            )
            .order_by(desc(SSLCertificate.created_at))
            .limit(limit)
        )
        certificates = result.scalars().all()

        # 히스토리 엔트리 구성
        history_entries = []
        for cert in certificates:
            # 오류 메시지 감지 (임시 구현)
            error_message = None
            if cert.status == SSLStatus.INVALID and "Error" in cert.issuer:
                error_message = f"SSL 체크 실패: {cert.issuer}"

            history_entries.append(SSLHistoryEntry(
                check_date=cert.created_at,
                status=cert.status.value,
                issuer=cert.issuer,
                expiry_date=cert.expiry_date,
                days_until_expiry=cert.days_until_expiry(),
                error_message=error_message
            ))

        return history_entries

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 히스토리 조회 중 오류가 발생했습니다"
        )


# 빠른 SSL 체크 (DB 저장 없음)

@router.post("/quick-check", response_model=QuickCheckResponse)
async def quick_ssl_check(
    request: SSLCheckRequest,
    ssl_service: SSLService = Depends(get_ssl_service)
) -> QuickCheckResponse:
    """
    빠른 SSL 체크

    URL의 SSL 인증서를 체크하되 DB에 저장하지 않는 빠른 체크입니다.
    """
    try:
        start_time = datetime.utcnow()

        # SSL 체크 수행
        from ..lib.ssl_checker import SSLChecker
        ssl_checker = SSLChecker(timeout=request.timeout)

        try:
            ssl_result = await ssl_checker.check_ssl_certificate(str(request.url))

            end_time = datetime.utcnow()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            return QuickCheckResponse(
                url=str(request.url),
                is_valid=ssl_result["status"].lower() == "valid",
                status=ssl_result["status"],
                certificate_info=ssl_result.get("certificate"),
                error_message=None,
                check_duration_ms=duration_ms,
                checked_at=end_time
            )

        except Exception as e:
            end_time = datetime.utcnow()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            return QuickCheckResponse(
                url=str(request.url),
                is_valid=False,
                status="error",
                certificate_info=None,
                error_message=str(e),
                check_duration_ms=duration_ms,
                checked_at=end_time
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 체크 중 오류가 발생했습니다"
        )