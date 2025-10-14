"""
시스템 설정 모델

전역 설정을 관리하는 싱글톤 모델입니다.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.orm import validates

from ..database import Base


class Settings(Base):
    """시스템 설정 모델 (싱글톤)"""

    __tablename__ = "settings"

    # Primary Key (항상 1로 고정하여 싱글톤 보장)
    id = Column(Integer, primary_key=True, default=1)

    # Webhook 설정
    webhook_url = Column(Text, nullable=True, comment="Teams/Power Automate 웹훅 URL")

    # 알림 설정
    notification_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="알림 활성화 여부"
    )
    notification_days_before = Column(
        String(100),
        nullable=False,
        default="30,7,1",
        comment="알림 발송 일수 (쉼표 구분)"
    )
    notification_language = Column(
        String(10),
        nullable=False,
        default="ko",
        comment="알림 언어 (ko/en)"
    )

    # 대시보드 URL
    dashboard_url = Column(
        String(500),
        nullable=True,
        comment="대시보드 URL (알림에 포함)"
    )

    # SSL 체크 설정
    ssl_timeout_seconds = Column(
        Integer,
        nullable=False,
        default=10,
        comment="SSL 체크 타임아웃 (초)"
    )
    max_concurrent_checks = Column(
        Integer,
        nullable=False,
        default=5,
        comment="최대 동시 SSL 체크 수"
    )

    # 타임스탬프
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="생성 시각"
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="수정 시각"
    )

    @validates("notification_days_before")
    def validate_notification_days(self, key, value):
        """알림 일수 검증"""
        if not value:
            return "30,7,1"

        # 쉼표로 분리하여 숫자인지 확인
        try:
            days = [int(day.strip()) for day in value.split(",")]
            if not all(day > 0 for day in days):
                raise ValueError("알림 일수는 양수여야 합니다")
            return value
        except (ValueError, AttributeError):
            return "30,7,1"

    @validates("notification_language")
    def validate_language(self, key, value):
        """언어 검증"""
        if value not in ["ko", "en"]:
            return "ko"
        return value

    @validates("ssl_timeout_seconds")
    def validate_timeout(self, key, value):
        """타임아웃 검증"""
        if not isinstance(value, int) or value < 1 or value > 60:
            return 10
        return value

    @validates("max_concurrent_checks")
    def validate_concurrent_checks(self, key, value):
        """동시 체크 수 검증"""
        if not isinstance(value, int) or value < 1 or value > 20:
            return 5
        return value

    def __repr__(self):
        return f"<Settings(id={self.id}, notification_enabled={self.notification_enabled})>"
