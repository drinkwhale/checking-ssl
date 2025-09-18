"""
웹사이트 관리 API 엔드포인트

웹사이트 CRUD 작업 및 SSL 체크 통합 API를 제공합니다.
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_async_session
from ..services.website_service import get_website_service, WebsiteService, WebsiteServiceError


# APIRouter 생성
router = APIRouter(prefix="/api/websites", tags=["websites"])


# Request/Response 모델 정의
class WebsiteCreateRequest(BaseModel):
    """웹사이트 생성 요청"""
    url: HttpUrl = Field(..., description="웹사이트 URL")
    name: Optional[str] = Field(None, description="표시명")
    auto_check_ssl: bool = Field(True, description="자동 SSL 체크 여부")


class WebsiteUpdateRequest(BaseModel):
    """웹사이트 업데이트 요청"""
    url: Optional[HttpUrl] = Field(None, description="새 URL")
    name: Optional[str] = Field(None, description="새 표시명")
    is_active: Optional[bool] = Field(None, description="활성 상태")


class WebsiteBatchCheckRequest(BaseModel):
    """일괄 SSL 체크 요청"""
    website_ids: Optional[List[str]] = Field(None, description="체크할 웹사이트 ID 목록")
    active_only: bool = Field(True, description="활성 웹사이트만 체크")


class WebsiteResponse(BaseModel):
    """웹사이트 응답"""
    website: Dict[str, Any] = Field(..., description="웹사이트 정보")
    ssl_certificate: Optional[Dict[str, Any]] = Field(None, description="SSL 인증서 정보")
    ssl_check_error: Optional[str] = Field(None, description="SSL 체크 오류")
    additional_info: Optional[Dict[str, Any]] = Field(None, description="추가 정보")


class BatchCheckResponse(BaseModel):
    """일괄 체크 응답"""
    total_websites: int = Field(..., description="총 웹사이트 수")
    successful_checks: int = Field(..., description="성공한 체크 수")
    failed_checks: int = Field(..., description="실패한 체크 수")
    results: List[Dict[str, Any]] = Field(..., description="체크 결과 목록")
    checked_at: str = Field(..., description="체크 시각")


class StatisticsResponse(BaseModel):
    """통계 응답"""
    total_websites: int = Field(..., description="전체 웹사이트 수")
    active_websites: int = Field(..., description="활성 웹사이트 수")
    ssl_status_distribution: Dict[str, int] = Field(..., description="SSL 상태별 분포")
    expiry_statistics: Dict[str, int] = Field(..., description="만료 임박 통계")
    generated_at: str = Field(..., description="생성 시각")


class ExpiringCertificatesResponse(BaseModel):
    """만료 임박 인증서 응답"""
    certificates: List[Dict[str, Any]] = Field(..., description="만료 임박 인증서 목록")
    total_count: int = Field(..., description="총 개수")
    days_criteria: int = Field(..., description="만료 기준 일수")


# API 엔드포인트 정의

@router.post("/", response_model=WebsiteResponse, status_code=status.HTTP_201_CREATED)
async def create_website(
    request: WebsiteCreateRequest,
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteResponse:
    """
    웹사이트 생성 및 SSL 체크

    새 웹사이트를 등록하고 선택적으로 SSL 인증서를 체크합니다.
    """
    try:
        result = await website_service.create_website_with_ssl_check(
            url=str(request.url),
            name=request.name,
            auto_check_ssl=request.auto_check_ssl
        )

        return WebsiteResponse(
            website=result["website"],
            ssl_certificate=result.get("ssl_certificate"),
            ssl_check_error=result.get("ssl_check_error"),
            additional_info={"created_at": datetime.utcnow().isoformat()}
        )

    except WebsiteServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="웹사이트 생성 중 내부 오류가 발생했습니다"
        )


@router.get("/", response_model=List[WebsiteResponse])
async def list_websites(
    active_only: bool = Query(False, description="활성 웹사이트만 조회"),
    include_ssl: bool = Query(True, description="SSL 정보 포함"),
    session: AsyncSession = Depends(get_async_session)
) -> List[WebsiteResponse]:
    """
    웹사이트 목록 조회

    등록된 웹사이트 목록을 조회하며, 옵션에 따라 SSL 정보도 함께 반환합니다.
    """
    try:
        website_service = WebsiteService(session)

        # 웹사이트 목록 조회
        from ..lib.website_manager import WebsiteManager
        website_manager = WebsiteManager(session)
        websites = await website_manager.get_all_websites(active_only=active_only)

        # 응답 구성
        responses = []
        for website in websites:
            website_data = {"website": website.to_dict()}

            if include_ssl:
                # 최신 SSL 정보 포함
                ssl_info = await website_service.get_website_with_latest_ssl(website.id)
                if ssl_info:
                    website_data.update({
                        "ssl_certificate": ssl_info.get("ssl_certificate"),
                        "ssl_check_error": None
                    })

            responses.append(WebsiteResponse(
                website=website_data["website"],
                ssl_certificate=website_data.get("ssl_certificate"),
                ssl_check_error=website_data.get("ssl_check_error")
            ))

        return responses

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="웹사이트 목록 조회 중 오류가 발생했습니다"
        )


@router.get("/{website_id}", response_model=WebsiteResponse)
async def get_website(
    website_id: str,
    include_ssl: bool = Query(True, description="SSL 정보 포함"),
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteResponse:
    """
    특정 웹사이트 조회

    웹사이트 ID로 특정 웹사이트 정보를 조회합니다.
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

        if include_ssl:
            website_info = await website_service.get_website_with_latest_ssl(uuid_id)
        else:
            from ..lib.website_manager import WebsiteManager
            website_manager = WebsiteManager(website_service.session)
            website = await website_manager.get_website_by_id(uuid_id)
            website_info = {"website": website.to_dict(), "ssl_certificate": None} if website else None

        if not website_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="웹사이트를 찾을 수 없습니다"
            )

        return WebsiteResponse(
            website=website_info["website"],
            ssl_certificate=website_info.get("ssl_certificate"),
            ssl_check_error=None
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="웹사이트 조회 중 오류가 발생했습니다"
        )


@router.put("/{website_id}", response_model=WebsiteResponse)
async def update_website(
    website_id: str,
    request: WebsiteUpdateRequest,
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteResponse:
    """
    웹사이트 정보 업데이트

    웹사이트 정보를 업데이트하며, URL 변경 시 SSL 재체크를 수행합니다.
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

        # 업데이트 수행
        result = await website_service.update_website_with_ssl_recheck(
            website_id=uuid_id,
            url=str(request.url) if request.url else None,
            name=request.name,
            is_active=request.is_active
        )

        additional_info = {
            "updated_at": datetime.utcnow().isoformat(),
            "ssl_rechecked": result.get("ssl_rechecked", False)
        }

        return WebsiteResponse(
            website=result["website"],
            ssl_certificate=result.get("ssl_certificate"),
            ssl_check_error=result.get("ssl_check_error"),
            additional_info=additional_info
        )

    except WebsiteServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="웹사이트 업데이트 중 오류가 발생했습니다"
        )


@router.delete("/{website_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_website(
    website_id: str,
    website_service: WebsiteService = Depends(get_website_service)
):
    """
    웹사이트 삭제

    웹사이트와 관련된 모든 SSL 인증서 정보를 함께 삭제합니다.
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

        # 삭제 수행
        success = await website_service.delete_website_with_cleanup(uuid_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="웹사이트를 찾을 수 없습니다"
            )

    except WebsiteServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="웹사이트 삭제 중 오류가 발생했습니다"
        )


@router.post("/{website_id}/ssl-check", response_model=WebsiteResponse)
async def manual_ssl_check(
    website_id: str,
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteResponse:
    """
    수동 SSL 체크

    특정 웹사이트의 SSL 인증서를 수동으로 체크합니다.
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

        # 수동 SSL 체크 수행
        result = await website_service.manual_ssl_check(uuid_id)

        return WebsiteResponse(
            website=result["website"],
            ssl_certificate=result.get("ssl_certificate"),
            ssl_check_error=result.get("ssl_check_error"),
            additional_info={
                "manual_check": result.get("manual_check", True),
                "checked_at": result.get("checked_at")
            }
        )

    except WebsiteServiceError as e:
        error_message = str(e)
        # 삭제된 웹사이트에 대한 SSL 체크 요청은 410 Gone으로 응답
        if "웹사이트를 찾을 수 없습니다" in error_message:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="요청한 웹사이트가 삭제되었거나 존재하지 않아 SSL 체크를 수행할 수 없습니다"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 체크 중 오류가 발생했습니다"
        )


@router.post("/batch-ssl-check", response_model=BatchCheckResponse)
async def batch_ssl_check(
    request: WebsiteBatchCheckRequest,
    website_service: WebsiteService = Depends(get_website_service)
) -> BatchCheckResponse:
    """
    일괄 SSL 체크

    여러 웹사이트의 SSL 인증서를 한 번에 체크합니다.
    """
    try:
        # UUID 목록 변환 (제공된 경우)
        website_ids = None
        if request.website_ids:
            try:
                website_ids = [uuid.UUID(id_str) for id_str in request.website_ids]
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="유효하지 않은 웹사이트 ID가 포함되어 있습니다"
                )

        # 일괄 SSL 체크 수행
        result = await website_service.batch_ssl_check(
            website_ids=website_ids,
            active_only=request.active_only
        )

        return BatchCheckResponse(**result)

    except WebsiteServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="일괄 SSL 체크 중 오류가 발생했습니다"
        )


@router.get("/ssl/expiring", response_model=ExpiringCertificatesResponse)
async def get_expiring_certificates(
    days: int = Query(30, ge=1, le=365, description="만료 임박 기준 일수"),
    website_service: WebsiteService = Depends(get_website_service)
) -> ExpiringCertificatesResponse:
    """
    만료 임박 인증서 조회

    지정된 일수 내에 만료되는 SSL 인증서 목록을 조회합니다.
    """
    try:
        certificates = await website_service.get_expiring_certificates(days=days)

        return ExpiringCertificatesResponse(
            certificates=certificates,
            total_count=len(certificates),
            days_criteria=days
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="만료 임박 인증서 조회 중 오류가 발생했습니다"
        )


@router.get("/ssl/statistics", response_model=StatisticsResponse)
async def get_ssl_statistics(
    website_service: WebsiteService = Depends(get_website_service)
) -> StatisticsResponse:
    """
    SSL 통계 조회

    SSL 인증서 관련 전반적인 통계 정보를 조회합니다.
    """
    try:
        statistics = await website_service.get_ssl_statistics()

        return StatisticsResponse(**statistics)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSL 통계 조회 중 오류가 발생했습니다"
        )