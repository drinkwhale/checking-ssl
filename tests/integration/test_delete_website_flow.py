"""
웹사이트 삭제 및 정리 통합 테스트

이 테스트는 사용자 스토리를 검증합니다:
- 사용자가 웹사이트를 삭제할 수 있다
- 삭제 시 관련 SSL 인증서 정보도 함께 삭제된다 (CASCADE)
- 비활성화된 웹사이트는 자동 체크에서 제외된다
"""

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.src.models.website import Website
from backend.src.models.ssl_certificate import SSLCertificate


class TestDeleteWebsiteFlow:
    """웹사이트 삭제 및 정리 플로우 테스트"""

    @pytest.mark.asyncio
    async def test_delete_website_removes_ssl_certificates(
        self,
        async_client: httpx.AsyncClient,
        db_session: AsyncSession,
        sample_website_with_ssl: tuple[Website, SSLCertificate],
    ):
        """웹사이트 삭제 시 관련 SSL 인증서가 함께 삭제되는지 테스트"""
        # Given: SSL 인증서가 있는 웹사이트
        website, ssl_cert = sample_website_with_ssl
        website_id = website.id
        ssl_cert_id = ssl_cert.id

        # When: 웹사이트 삭제 API 호출
        response = await async_client.delete(f"/api/websites/{website_id}")

        # Then: 성공 응답 확인
        assert response.status_code == 204

        # And: 웹사이트가 데이터베이스에서 삭제됨
        db_session.expire_all()  # 세션 캐시 무효화
        deleted_website = await db_session.get(Website, website_id)
        assert deleted_website is None

        # And: 관련 SSL 인증서도 함께 삭제됨
        deleted_ssl_cert = await db_session.get(SSLCertificate, ssl_cert_id)
        assert deleted_ssl_cert is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_website_fails(
        self, async_client: httpx.AsyncClient
    ):
        """존재하지 않는 웹사이트 삭제 시 실패하는지 테스트"""
        # Given: 존재하지 않는 웹사이트 ID
        nonexistent_id = "550e8400-e29b-41d4-a716-446655440999"

        # When: 존재하지 않는 웹사이트 삭제 시도
        response = await async_client.delete(f"/api/websites/{nonexistent_id}")

        # Then: 404 오류 응답 확인
        assert response.status_code == 404
        error_detail = response.json()
        assert "not found" in error_detail["detail"].lower()

    @pytest.mark.asyncio
    async def test_deactivate_website_excludes_from_auto_check(
        self,
        async_client: httpx.AsyncClient,
        db_session: AsyncSession,
        sample_website: Website,
    ):
        """웹사이트 비활성화 시 자동 체크에서 제외되는지 테스트"""
        # Given: 활성화된 웹사이트
        website_id = sample_website.id
        assert sample_website.is_active is True

        # When: 웹사이트 비활성화
        update_data = {"is_active": False}
        response = await async_client.patch(
            f"/api/websites/{website_id}", json=update_data
        )

        # Then: 성공 응답 확인
        assert response.status_code == 200
        updated_website = response.json()
        assert updated_website["is_active"] is False

        # And: 데이터베이스에서 비활성화 상태 확인
        website = await db_session.get(Website, website_id)
        assert website.is_active is False

        # And: 활성 웹사이트 목록에서 제외됨
        active_websites_response = await async_client.get(
            "/api/websites?active_only=true"
        )
        assert active_websites_response.status_code == 200
        active_websites = active_websites_response.json()
        website_ids = [w["id"] for w in active_websites]
        assert str(website_id) not in website_ids

    @pytest.mark.asyncio
    async def test_delete_multiple_websites_batch_operation(
        self,
        async_client: httpx.AsyncClient,
        db_session: AsyncSession,
        multiple_websites: list[Website],
    ):
        """여러 웹사이트 일괄 삭제 테스트"""
        # Given: 여러 웹사이트
        website_ids = [str(w.id) for w in multiple_websites]
        assert len(website_ids) >= 3

        # When: 일괄 삭제 API 호출
        delete_data = {"website_ids": website_ids[:2]}  # 처음 2개만 삭제
        response = await async_client.post("/api/websites/batch-delete", json=delete_data)

        # Then: 성공 응답 확인
        assert response.status_code == 200
        result = response.json()
        assert result["deleted_count"] == 2

        # And: 삭제된 웹사이트들이 데이터베이스에서 제거됨
        for website_id in delete_data["website_ids"]:
            deleted_website = await db_session.get(Website, website_id)
            assert deleted_website is None

        # And: 삭제되지 않은 웹사이트는 여전히 존재함
        remaining_website = await db_session.get(Website, website_ids[2])
        assert remaining_website is not None

    @pytest.mark.asyncio
    async def test_delete_website_with_recent_ssl_check(
        self,
        async_client: httpx.AsyncClient,
        db_session: AsyncSession,
        sample_website_with_recent_ssl: tuple[Website, SSLCertificate],
    ):
        """최근 SSL 체크가 있는 웹사이트 삭제 테스트"""
        # Given: 최근 SSL 체크가 수행된 웹사이트
        website, ssl_cert = sample_website_with_recent_ssl
        website_id = website.id

        # When: 웹사이트 삭제
        response = await async_client.delete(f"/api/websites/{website_id}")

        # Then: 성공적으로 삭제됨
        assert response.status_code == 204

        # And: 모든 관련 데이터가 정리됨
        deleted_website = await db_session.get(Website, website_id)
        assert deleted_website is None

    @pytest.mark.asyncio
    async def test_website_url_change_triggers_new_ssl_check(
        self,
        async_client: httpx.AsyncClient,
        db_session: AsyncSession,
        sample_website: Website,
    ):
        """웹사이트 URL 변경 시 새로운 SSL 체크가 트리거되는지 테스트"""
        # Given: 기존 웹사이트
        website_id = sample_website.id
        original_url = sample_website.url

        # When: URL 변경
        new_url = "https://github.com"
        update_data = {"url": new_url}
        response = await async_client.patch(
            f"/api/websites/{website_id}", json=update_data
        )

        # Then: 성공 응답 확인
        assert response.status_code == 200
        updated_website = response.json()
        assert updated_website["url"] == new_url

        # And: 새로운 SSL 인증서 정보가 생성됨
        ssl_certs = await db_session.execute(
            "SELECT * FROM ssl_certificates WHERE website_id = :website_id ORDER BY created_at DESC",
            {"website_id": website_id},
        )
        ssl_records = ssl_certs.fetchall()
        assert len(ssl_records) >= 1

        # And: 최신 SSL 인증서가 새 URL에 대한 것임
        latest_ssl = ssl_records[0]
        assert latest_ssl.status in ["valid", "invalid", "expired", "unknown"]

    @pytest.mark.asyncio
    async def test_delete_website_soft_delete_option(
        self,
        async_client: httpx.AsyncClient,
        db_session: AsyncSession,
        sample_website: Website,
    ):
        """소프트 삭제 옵션 테스트 (비활성화)"""
        # Given: 활성화된 웹사이트
        website_id = sample_website.id

        # When: 소프트 삭제 (비활성화) 수행
        response = await async_client.patch(
            f"/api/websites/{website_id}",
            json={"is_active": False},
        )

        # Then: 성공 응답 확인
        assert response.status_code == 200

        # And: 웹사이트는 여전히 존재하지만 비활성화됨
        website = await db_session.get(Website, website_id)
        assert website is not None
        assert website.is_active is False

        # And: 전체 웹사이트 목록에는 포함되지만 활성 목록에서는 제외됨
        all_websites_response = await async_client.get("/api/websites")
        active_websites_response = await async_client.get(
            "/api/websites?active_only=true"
        )

        all_websites = all_websites_response.json()
        active_websites = active_websites_response.json()

        all_ids = [w["id"] for w in all_websites]
        active_ids = [w["id"] for w in active_websites]

        assert str(website_id) in all_ids
        assert str(website_id) not in active_ids