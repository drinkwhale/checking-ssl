"""
시스템 설정 API

시스템 설정을 조회하고 업데이트하는 API 엔드포인트입니다.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_async_session
from ..lib.settings_manager import SettingsManager, SettingsManagerError


# API 라우터 생성
router = APIRouter(prefix="/api/settings", tags=["settings"])


# Pydantic 모델
class SettingsResponse(BaseModel):
    """시스템 설정 응답 모델"""
    webhook_url: Optional[str] = Field(None, description="Teams/Power Automate 웹훅 URL")
    notification_enabled: bool = Field(True, description="알림 활성화 여부")
    notification_days_before: str = Field("30,7,1", description="알림 발송 일수 (쉼표 구분)")
    notification_language: str = Field("ko", description="알림 언어 (ko/en)")
    dashboard_url: Optional[str] = Field(None, description="대시보드 URL")
    ssl_timeout_seconds: int = Field(10, description="SSL 체크 타임아웃 (초)")
    max_concurrent_checks: int = Field(5, description="최대 동시 SSL 체크 수")
    created_at: Optional[str] = Field(None, description="생성 시각")
    updated_at: Optional[str] = Field(None, description="수정 시각")

    class Config:
        from_attributes = True


class SettingsUpdateRequest(BaseModel):
    """시스템 설정 업데이트 요청 모델"""
    webhook_url: Optional[str] = Field(None, description="Teams/Power Automate 웹훅 URL")
    notification_enabled: Optional[bool] = Field(None, description="알림 활성화 여부")
    notification_days_before: Optional[str] = Field(None, description="알림 발송 일수 (쉼표 구분)")
    notification_language: Optional[str] = Field(None, description="알림 언어 (ko/en)")
    dashboard_url: Optional[str] = Field(None, description="대시보드 URL")
    ssl_timeout_seconds: Optional[int] = Field(None, ge=1, le=60, description="SSL 체크 타임아웃 (초)")
    max_concurrent_checks: Optional[int] = Field(None, ge=1, le=20, description="최대 동시 SSL 체크 수")

    @validator("notification_days_before")
    def validate_notification_days(cls, v):
        """알림 일수 검증"""
        if v is None:
            return v

        try:
            days = [int(day.strip()) for day in v.split(",")]
            if not all(day > 0 for day in days):
                raise ValueError("알림 일수는 양수여야 합니다")
            return v
        except (ValueError, AttributeError):
            raise ValueError("알림 일수 형식이 올바르지 않습니다 (예: 30,7,1)")

    @validator("notification_language")
    def validate_language(cls, v):
        """언어 검증"""
        if v is not None and v not in ["ko", "en"]:
            raise ValueError("언어는 'ko' 또는 'en'이어야 합니다")
        return v


class WebhookTestRequest(BaseModel):
    """Webhook 테스트 요청 모델"""
    webhook_url: Optional[str] = Field(None, description="테스트할 웹훅 URL (없으면 설정된 URL 사용)")


# API 엔드포인트
@router.get("", response_model=SettingsResponse)
async def get_settings(
    session: AsyncSession = Depends(get_async_session)
):
    """
    시스템 설정 조회

    전역 설정을 조회합니다. 설정이 없으면 기본값으로 생성됩니다.
    """
    try:
        manager = SettingsManager(session)
        settings = await manager.get_settings()
        return manager.to_dict(settings)

    except SettingsManagerError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("", response_model=SettingsResponse)
async def update_settings(
    request: SettingsUpdateRequest,
    session: AsyncSession = Depends(get_async_session)
):
    """
    시스템 설정 업데이트

    제공된 필드만 업데이트됩니다. None 값은 무시됩니다.
    """
    try:
        manager = SettingsManager(session)

        # None이 아닌 필드만 딕셔너리로 변환
        updates = {
            key: value
            for key, value in request.dict().items()
            if value is not None
        }

        if not updates:
            raise HTTPException(status_code=400, detail="업데이트할 필드가 없습니다")

        settings = await manager.update_settings(updates)
        return manager.to_dict(settings)

    except SettingsManagerError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/test-webhook")
async def test_webhook(
    request: WebhookTestRequest,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Webhook 테스트

    Webhook URL로 테스트 메시지를 발송합니다.
    """
    try:
        from ..lib.notification_service import NotificationService

        # Webhook URL 결정 (요청에 있으면 우선, 없으면 설정에서 가져오기)
        webhook_url = request.webhook_url
        if not webhook_url:
            manager = SettingsManager(session)
            webhook_url = await manager.get_webhook_url()

        if not webhook_url:
            raise HTTPException(
                status_code=400,
                detail="Webhook URL이 설정되지 않았습니다"
            )

        # 알림 서비스 초기화 및 테스트
        notification_service = NotificationService(
            session=session,
            webhook_url=webhook_url
        )

        success = await notification_service.test_notification()

        if success:
            return {
                "success": True,
                "message": "테스트 메시지가 성공적으로 발송되었습니다"
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="테스트 메시지 발송에 실패했습니다"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook 테스트 실패: {str(e)}")
