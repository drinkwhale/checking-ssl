"""
헬스체크 API 엔드포인트

시스템 상태, 라이브니스, 레디니스, 메트릭 등의 헬스체크 API를 제공합니다.
"""

import asyncio
import time
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from ..database import get_async_session, get_engine
from ..models.website import Website
from ..models.ssl_certificate import SSLCertificate, SSLStatus


# APIRouter 생성
router = APIRouter(prefix="/api/health", tags=["health"])


# Response 모델 정의
class SystemHealth(BaseModel):
    """시스템 헬스 상태"""
    status: str = Field(..., description="전체 상태 (healthy, degraded, unhealthy)")
    timestamp: datetime = Field(..., description="체크 시간")
    uptime_seconds: float = Field(..., description="업타임 (초)")
    version: str = Field("1.0.0", description="애플리케이션 버전")

    database: Dict[str, Any] = Field(..., description="데이터베이스 상태")
    system: Dict[str, Any] = Field(..., description="시스템 리소스 상태")
    ssl_monitoring: Dict[str, Any] = Field(..., description="SSL 모니터링 상태")


class LivenessCheck(BaseModel):
    """라이브니스 체크"""
    alive: bool = Field(..., description="생존 여부")
    timestamp: datetime = Field(..., description="체크 시간")


class ReadinessCheck(BaseModel):
    """레디니스 체크"""
    ready: bool = Field(..., description="준비 상태")
    timestamp: datetime = Field(..., description="체크 시간")
    checks: Dict[str, Any] = Field(..., description="개별 체크 결과")


class MetricsResponse(BaseModel):
    """메트릭 응답"""
    timestamp: datetime = Field(..., description="수집 시간")
    system_metrics: Dict[str, Any] = Field(..., description="시스템 메트릭")
    application_metrics: Dict[str, Any] = Field(..., description="애플리케이션 메트릭")
    database_metrics: Dict[str, Any] = Field(..., description="데이터베이스 메트릭")


# 전역 변수 (애플리케이션 시작 시간)
_app_start_time = time.time()


# 헬스체크 유틸리티 함수
async def check_database_health(session: AsyncSession) -> Dict[str, Any]:
    """데이터베이스 헬스 체크"""
    try:
        start_time = time.time()

        # 간단한 쿼리 실행
        await session.execute(text("SELECT 1"))

        response_time = (time.time() - start_time) * 1000  # ms

        # 연결 풀 상태 확인
        engine = get_engine()
        pool = engine.pool
        pool_status = {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "invalid": pool.invalid()
        }

        return {
            "status": "healthy",
            "response_time_ms": round(response_time, 2),
            "pool_status": pool_status,
            "error": None
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "response_time_ms": None,
            "pool_status": None,
            "error": str(e)
        }


def get_system_metrics() -> Dict[str, Any]:
    """시스템 메트릭 수집"""
    try:
        # CPU 사용률
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # 메모리 사용률
        memory = psutil.virtual_memory()
        memory_info = {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "used_bytes": memory.used,
            "used_percent": memory.percent
        }

        # 디스크 사용률
        disk = psutil.disk_usage('/')
        disk_info = {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "used_percent": (disk.used / disk.total) * 100
        }

        # 네트워크 통계
        net_io = psutil.net_io_counters()
        network_info = {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv
        }

        return {
            "cpu_percent": cpu_percent,
            "memory": memory_info,
            "disk": disk_info,
            "network": network_info,
            "load_average": list(psutil.getloadavg()) if hasattr(psutil, 'getloadavg') else None
        }

    except Exception as e:
        return {"error": str(e)}


async def check_ssl_monitoring_health(session: AsyncSession) -> Dict[str, Any]:
    """SSL 모니터링 시스템 헬스 체크"""
    try:
        # 웹사이트 및 인증서 수 조회
        websites_result = await session.execute(
            select(Website.id).where(Website.is_active == True)
        )
        active_websites = len(websites_result.all())

        # 최근 24시간 내 SSL 체크 수
        yesterday = datetime.utcnow() - timedelta(hours=24)
        recent_checks_result = await session.execute(
            select(SSLCertificate.id).where(SSLCertificate.created_at >= yesterday)
        )
        recent_ssl_checks = len(recent_checks_result.all())

        # 오류 상태 인증서 수
        error_certs_result = await session.execute(
            select(SSLCertificate.id)
            .join(Website, Website.id == SSLCertificate.website_id)
            .where(
                Website.is_active == True,
                SSLCertificate.status == SSLStatus.INVALID
            )
        )
        error_certificates = len(error_certs_result.all())

        # 만료 임박 인증서 수
        week_later = datetime.utcnow() + timedelta(days=7)
        expiring_soon_result = await session.execute(
            select(SSLCertificate.id)
            .join(Website, Website.id == SSLCertificate.website_id)
            .where(
                Website.is_active == True,
                SSLCertificate.status == SSLStatus.VALID,
                SSLCertificate.expiry_date <= week_later,
                SSLCertificate.expiry_date > datetime.utcnow()
            )
        )
        expiring_soon = len(expiring_soon_result.all())

        # 상태 판정
        status = "healthy"
        if error_certificates > active_websites * 0.5:  # 50% 이상 오류
            status = "unhealthy"
        elif error_certificates > active_websites * 0.2 or expiring_soon > 10:  # 20% 이상 오류 또는 10개 이상 만료 임박
            status = "degraded"

        return {
            "status": status,
            "active_websites": active_websites,
            "recent_ssl_checks_24h": recent_ssl_checks,
            "error_certificates": error_certificates,
            "expiring_soon_7days": expiring_soon,
            "error": None
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# API 엔드포인트

@router.get("/", response_model=SystemHealth)
async def health_check(
    session: AsyncSession = Depends(get_async_session)
) -> SystemHealth:
    """
    전체 시스템 헬스체크

    시스템의 전반적인 상태를 종합적으로 점검합니다.
    """
    timestamp = datetime.utcnow()
    uptime_seconds = time.time() - _app_start_time

    # 각 컴포넌트 헬스체크
    database_health = await check_database_health(session)
    system_health = get_system_metrics()
    ssl_monitoring_health = await check_ssl_monitoring_health(session)

    # 전체 상태 판정
    overall_status = "healthy"

    if (database_health.get("status") == "unhealthy" or
        ssl_monitoring_health.get("status") == "unhealthy"):
        overall_status = "unhealthy"
    elif (database_health.get("status") == "degraded" or
          ssl_monitoring_health.get("status") == "degraded"):
        overall_status = "degraded"

    # 시스템 리소스 기반 상태 조정
    if system_health.get("cpu_percent", 0) > 90:
        overall_status = "degraded" if overall_status == "healthy" else "unhealthy"

    if system_health.get("memory", {}).get("used_percent", 0) > 90:
        overall_status = "degraded" if overall_status == "healthy" else "unhealthy"

    return SystemHealth(
        status=overall_status,
        timestamp=timestamp,
        uptime_seconds=round(uptime_seconds, 2),
        version="1.0.0",
        database=database_health,
        system=system_health,
        ssl_monitoring=ssl_monitoring_health
    )


@router.get("/liveness", response_model=LivenessCheck)
async def liveness_check() -> LivenessCheck:
    """
    라이브니스 체크

    애플리케이션이 살아있는지 확인하는 기본적인 헬스체크입니다.
    Kubernetes liveness probe에서 사용됩니다.
    """
    return LivenessCheck(
        alive=True,
        timestamp=datetime.utcnow()
    )


@router.get("/readiness", response_model=ReadinessCheck)
async def readiness_check(
    session: AsyncSession = Depends(get_async_session)
) -> ReadinessCheck:
    """
    레디니스 체크

    애플리케이션이 트래픽을 받을 준비가 되었는지 확인합니다.
    Kubernetes readiness probe에서 사용됩니다.
    """
    checks = {}
    ready = True

    # 데이터베이스 연결 체크
    db_check = await check_database_health(session)
    checks["database"] = {
        "ready": db_check["status"] != "unhealthy",
        "response_time_ms": db_check.get("response_time_ms"),
        "error": db_check.get("error")
    }

    if not checks["database"]["ready"]:
        ready = False

    # 필수 테이블 존재 체크
    try:
        await session.execute(select(Website.id).limit(1))
        await session.execute(select(SSLCertificate.id).limit(1))
        checks["database_schema"] = {"ready": True, "error": None}
    except Exception as e:
        checks["database_schema"] = {"ready": False, "error": str(e)}
        ready = False

    return ReadinessCheck(
        ready=ready,
        timestamp=datetime.utcnow(),
        checks=checks
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    session: AsyncSession = Depends(get_async_session)
) -> MetricsResponse:
    """
    시스템 메트릭 조회

    시스템 리소스, 애플리케이션, 데이터베이스 메트릭을 수집합니다.
    모니터링 시스템에서 사용할 수 있습니다.
    """
    timestamp = datetime.utcnow()

    # 시스템 메트릭
    system_metrics = get_system_metrics()

    # 애플리케이션 메트릭
    uptime_seconds = time.time() - _app_start_time
    application_metrics = {
        "uptime_seconds": round(uptime_seconds, 2),
        "version": "1.0.0",
        "start_time": datetime.fromtimestamp(_app_start_time).isoformat()
    }

    # 데이터베이스 메트릭
    try:
        # 테이블별 레코드 수
        websites_count = await session.execute(select(Website.id))
        active_websites_count = await session.execute(
            select(Website.id).where(Website.is_active == True)
        )
        certificates_count = await session.execute(select(SSLCertificate.id))

        # SSL 상태별 분포
        valid_certs = await session.execute(
            select(SSLCertificate.id).where(SSLCertificate.status == SSLStatus.VALID)
        )
        expired_certs = await session.execute(
            select(SSLCertificate.id).where(SSLCertificate.status == SSLStatus.EXPIRED)
        )
        invalid_certs = await session.execute(
            select(SSLCertificate.id).where(SSLCertificate.status == SSLStatus.INVALID)
        )

        # 최근 활동
        yesterday = datetime.utcnow() - timedelta(hours=24)
        recent_certificates = await session.execute(
            select(SSLCertificate.id).where(SSLCertificate.created_at >= yesterday)
        )

        database_metrics = {
            "total_websites": len(websites_count.all()),
            "active_websites": len(active_websites_count.all()),
            "total_certificates": len(certificates_count.all()),
            "valid_certificates": len(valid_certs.all()),
            "expired_certificates": len(expired_certs.all()),
            "invalid_certificates": len(invalid_certs.all()),
            "certificates_last_24h": len(recent_certificates.all())
        }

    except Exception as e:
        database_metrics = {"error": str(e)}

    return MetricsResponse(
        timestamp=timestamp,
        system_metrics=system_metrics,
        application_metrics=application_metrics,
        database_metrics=database_metrics
    )


@router.get("/ping")
async def ping():
    """
    간단한 핑 엔드포인트

    로드밸런서나 간단한 헬스체크에서 사용할 수 있습니다.
    """
    return {"message": "pong", "timestamp": datetime.utcnow().isoformat()}


@router.get("/version")
async def get_version():
    """
    애플리케이션 버전 정보

    현재 실행 중인 애플리케이션의 버전 정보를 제공합니다.
    """
    return {
        "version": "1.0.0",
        "build_date": "2024-01-01",
        "commit_hash": "dev",
        "uptime_seconds": round(time.time() - _app_start_time, 2)
    }