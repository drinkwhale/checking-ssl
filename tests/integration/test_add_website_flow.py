"""
웹사이트 추가 및 SSL 체크 통합 테스트

이 테스트는 사용자 스토리를 검증합니다:
- 사용자가 웹사이트를 추가할 수 있다
- 추가된 웹사이트의 SSL 인증서가 자동으로 체크된다
- SSL 정보가 데이터베이스에 저장된다
"""

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.website import Website
from src.models.ssl_certificate import SSLCertificate


class TestAddWebsiteFlow:
    """웹사이트 추가 및 SSL 체크 플로우 테스트"""

    @pytest.mark.asyncio
    async def test_add_valid_website_creates_ssl_record(
        self, async_client: httpx.AsyncClient, db_session: AsyncSession
    ):
        """유효한 웹사이트 추가 시 SSL 인증서 레코드가 생성되는지 테스트"""
        # Given: 유효한 HTTPS 웹사이트 URL
        website_data = {
            "url": "https://google.com",
            "name": "Google",
        }

        # When: 웹사이트 추가 API 호출
        response = await async_client.post("/api/websites", json=website_data)

        # Then: 성공 응답 확인
        assert response.status_code == 201
        created_website = response.json()
        assert created_website["url"] == website_data["url"]
        assert created_website["name"] == website_data["name"]
        assert created_website["is_active"] is True

        # And: 데이터베이스에 웹사이트가 저장됨
        website_id = created_website["id"]
        website = await db_session.get(Website, website_id)
        assert website is not None
        assert website.url == website_data["url"]

        # And: SSL 인증서 정보가 자동으로 생성됨
        ssl_cert = await db_session.execute(
            "SELECT * FROM ssl_certificates WHERE website_id = :website_id",
            {"website_id": website_id},
        )
        ssl_record = ssl_cert.first()
        assert ssl_record is not None
        assert ssl_record.status in ["valid", "invalid", "expired"]
        assert ssl_record.expiry_date is not None

    @pytest.mark.asyncio
    async def test_add_website_with_invalid_url_fails(
        self, async_client: httpx.AsyncClient
    ):
        """잘못된 URL로 웹사이트 추가 시 실패하는지 테스트"""
        # Given: 잘못된 URL 형식
        invalid_urls = [
            {"url": "http://example.com", "name": "HTTP Site"},  # HTTP 불허
            {"url": "https://", "name": "Empty Domain"},  # 도메인 없음
            {"url": "not-a-url", "name": "Invalid Format"},  # URL 형식 아님
            {"url": "https://example.com/path", "name": "With Path"},  # 경로 포함
        ]

        for website_data in invalid_urls:
            # When: 잘못된 웹사이트 추가 시도
            response = await async_client.post("/api/websites", json=website_data)

            # Then: 실패 응답 확인
            assert response.status_code == 422  # Validation Error
            error_detail = response.json()
            assert "detail" in error_detail

    @pytest.mark.asyncio
    async def test_add_duplicate_website_fails(
        self, async_client: httpx.AsyncClient, sample_website: Website
    ):
        """중복 웹사이트 추가 시 실패하는지 테스트"""
        # Given: 이미 존재하는 웹사이트와 같은 URL
        duplicate_data = {
            "url": sample_website.url,
            "name": "Duplicate Site",
        }

        # When: 중복 웹사이트 추가 시도
        response = await async_client.post("/api/websites", json=duplicate_data)

        # Then: 중복 오류 응답 확인
        assert response.status_code == 409  # Conflict
        error_detail = response.json()
        assert "already exists" in error_detail["detail"].lower()

    @pytest.mark.asyncio
    async def test_add_website_ssl_check_timeout_handling(
        self, async_client: httpx.AsyncClient, db_session: AsyncSession
    ):
        """SSL 체크 타임아웃 시 적절히 처리되는지 테스트"""
        # Given: 타임아웃이 발생할 수 있는 웹사이트
        website_data = {
            "url": "https://httpstat.us/200?sleep=15000",  # 15초 지연
            "name": "Timeout Test",
        }

        # When: 웹사이트 추가 (타임아웃 설정은 10초)
        response = await async_client.post("/api/websites", json=website_data)

        # Then: 웹사이트는 추가되지만 SSL 상태는 unknown
        assert response.status_code == 201
        created_website = response.json()

        # And: SSL 인증서 상태가 unknown 또는 invalid로 설정됨
        website_id = created_website["id"]
        ssl_cert = await db_session.execute(
            "SELECT * FROM ssl_certificates WHERE website_id = :website_id",
            {"website_id": website_id},
        )
        ssl_record = ssl_cert.first()
        assert ssl_record is not None
        assert ssl_record.status in ["unknown", "invalid"]

    @pytest.mark.asyncio
    async def test_add_website_auto_ssl_check_performance(
        self, async_client: httpx.AsyncClient
    ):
        """웹사이트 추가 시 SSL 체크 성능 테스트 (5초 이내)"""
        import time

        # Given: 빠른 응답을 하는 웹사이트
        website_data = {
            "url": "https://www.google.com",
            "name": "Performance Test",
        }

        # When: 웹사이트 추가 및 시간 측정
        start_time = time.time()
        response = await async_client.post("/api/websites", json=website_data)
        end_time = time.time()

        # Then: 성공 응답 및 성능 요구사항 확인
        assert response.status_code == 201
        assert (end_time - start_time) < 5.0  # 5초 이내 완료

    @pytest.mark.asyncio
    async def test_add_website_with_custom_port(
        self, async_client: httpx.AsyncClient, db_session: AsyncSession
    ):
        """커스텀 포트를 가진 웹사이트 추가 테스트"""
        # Given: 커스텀 포트를 가진 웹사이트
        website_data = {
            "url": "https://badssl.com:443",
            "name": "Custom Port Test",
        }

        # When: 웹사이트 추가
        response = await async_client.post("/api/websites", json=website_data)

        # Then: 성공적으로 추가됨
        assert response.status_code == 201
        created_website = response.json()
        assert created_website["url"] == website_data["url"]

        # And: SSL 인증서 정보가 생성됨
        website_id = created_website["id"]
        ssl_cert = await db_session.execute(
            "SELECT * FROM ssl_certificates WHERE website_id = :website_id",
            {"website_id": website_id},
        )
        ssl_record = ssl_cert.first()
        assert ssl_record is not None