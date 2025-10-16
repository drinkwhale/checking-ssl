/**
 * SSL Certificate Monitor API 클라이언트
 *
 * REST API 호출, 오류 처리, UI 업데이트를 담당하는 클라이언트입니다.
 */

class SSLMonitorAPI {
    constructor() {
        // API 기본 설정
        this.baseURL = window.location.origin;
        this.apiPrefix = '/api';
        this.timeout = 30000; // 30초

        // 요청 인터셉터
        this.requestInterceptors = [];
        this.responseInterceptors = [];

        // 에러 핸들러
        this.errorHandlers = new Map();

        this.initialized = false;
    }

    /**
     * API 클라이언트 초기화
     */
    init() {
        if (this.initialized) return;

        // 기본 에러 핸들러 등록
        this.setupDefaultErrorHandlers();

        // API 모듈 초기화
        this.websites = new WebsitesAPI(this);
        this.ssl = new SSLAPI(this);
        this.health = new HealthAPI(this);
        this.tasks = new TasksAPI(this);
        this.settings = new SettingsAPI(this);

        this.initialized = true;
        console.log('SSL Monitor API 클라이언트가 초기화되었습니다');
    }

    /**
     * HTTP 요청 수행
     */
    async request(method, endpoint, options = {}) {
        const url = `${this.baseURL}${this.apiPrefix}${endpoint}`;

        // 기본 설정
        const config = {
            method: method.toUpperCase(),
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };

        // 요청 바디 처리
        if (config.body && typeof config.body === 'object' && !(config.body instanceof FormData)) {
            config.body = JSON.stringify(config.body);
        }

        // 요청 인터셉터 실행
        for (const interceptor of this.requestInterceptors) {
            await interceptor(config);
        }

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.timeout);

            config.signal = controller.signal;

            const response = await fetch(url, config);
            clearTimeout(timeoutId);

            // 응답 인터셉터 실행
            for (const interceptor of this.responseInterceptors) {
                await interceptor(response);
            }

            return await this.handleResponse(response);

        } catch (error) {
            if (error.name === 'AbortError') {
                throw new APIError('요청 시간이 초과되었습니다', 'TIMEOUT');
            }

            if (error instanceof APIError) {
                throw error;
            }

            // 네트워크 오류
            throw new APIError('네트워크 연결에 실패했습니다', 'NETWORK_ERROR', error);
        }
    }

    /**
     * 응답 처리
     */
    async handleResponse(response) {
        // 204 No Content 응답 처리
        if (response.status === 204) {
            return null;
        }

        const contentType = response.headers.get('content-type');

        let data;
        if (contentType && contentType.includes('application/json')) {
            try {
                data = await response.json();
            } catch (error) {
                throw new APIError('응답 데이터를 파싱할 수 없습니다', 'PARSE_ERROR', error);
            }
        } else {
            try {
                data = await response.text();
            } catch (error) {
                throw new APIError('응답 데이터를 읽을 수 없습니다', 'PARSE_ERROR', error);
            }
        }

        if (!response.ok) {
            const message = data?.message || data?.detail || `HTTP ${response.status} 오류`;
            const errorCode = data?.error_code || `HTTP_${response.status}`;

            throw new APIError(message, errorCode, null, response.status, data);
        }

        return data;
    }

    /**
     * 기본 에러 핸들러 설정
     */
    setupDefaultErrorHandlers() {
        // 네트워크 오류
        this.errorHandlers.set('NETWORK_ERROR', (error) => {
            console.error('네트워크 오류:', error);
            this.showError('네트워크 연결을 확인해주세요');
        });

        // 타임아웃
        this.errorHandlers.set('TIMEOUT', (error) => {
            console.error('요청 타임아웃:', error);
            this.showError('서버 응답 시간이 초과되었습니다');
        });

        // 인증 오류
        this.errorHandlers.set('UNAUTHORIZED', (error) => {
            console.error('인증 오류:', error);
            this.showError('인증이 필요합니다');
        });

        // 리소스 삭제됨
        this.errorHandlers.set('HTTP_410', (error) => {
            console.warn('삭제된 리소스 요청:', error);
            this.showError('요청한 웹사이트가 삭제되었습니다');
        });

        // 서버 오류
        this.errorHandlers.set('INTERNAL_SERVER_ERROR', (error) => {
            console.error('서버 오류:', error);
            this.showError('서버에서 오류가 발생했습니다');
        });

        // 기본 오류
        this.errorHandlers.set('DEFAULT', (error) => {
            console.error('API 오류:', error);
            this.showError(error.message || '알 수 없는 오류가 발생했습니다');
        });
    }

    /**
     * 오류 처리
     */
    handleError(error) {
        const handler = this.errorHandlers.get(error.code) || this.errorHandlers.get('DEFAULT');
        handler(error);
    }

    /**
     * 에러 메시지 표시
     */
    showError(message) {
        // HTML의 showToast 함수 사용
        if (typeof showToast === 'function') {
            showToast(message, 'error');
        } else {
            alert(message);
        }
    }

    /**
     * 성공 메시지 표시
     */
    showSuccess(message) {
        if (typeof showToast === 'function') {
            showToast(message, 'success');
        }
    }

    // HTTP 메서드 헬퍼
    async get(endpoint, params = {}) {
        // 쿼리 파라미터 문자열 생성
        const queryString = Object.keys(params)
            .filter(key => params[key] !== null && params[key] !== undefined)
            .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
            .join('&');

        // 엔드포인트에 쿼리 문자열 추가
        const fullEndpoint = queryString ? `${endpoint}?${queryString}` : endpoint;

        return this.request('GET', fullEndpoint);
    }

    async post(endpoint, data = {}) {
        return this.request('POST', endpoint, { body: data });
    }

    async put(endpoint, data = {}) {
        return this.request('PUT', endpoint, { body: data });
    }

    async delete(endpoint) {
        return this.request('DELETE', endpoint);
    }
}

/**
 * API 오류 클래스
 */
class APIError extends Error {
    constructor(message, code = 'UNKNOWN', originalError = null, status = null, response = null) {
        super(message);
        this.name = 'APIError';
        this.code = code;
        this.originalError = originalError;
        this.status = status;
        this.response = response;
    }
}

/**
 * 웹사이트 API
 */
class WebsitesAPI {
    constructor(client) {
        this.client = client;
    }

    /**
     * 웹사이트 목록 조회
     */
    async list(params = {}) {
        try {
            return await this.client.get('/websites', params);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 웹사이트 상세 조회
     */
    async get(websiteId, params = {}) {
        try {
            return await this.client.get(`/websites/${websiteId}`, params);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 웹사이트 생성
     */
    async create(data) {
        try {
            // trailing slash 포함하여 307 리다이렉트 방지
            const result = await this.client.post('/websites/', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 웹사이트 수정
     */
    async update(websiteId, data) {
        try {
            const result = await this.client.put(`/websites/${websiteId}`, data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 웹사이트 삭제
     */
    async delete(websiteId) {
        try {
            const result = await this.client.delete(`/websites/${websiteId}`);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 수동 SSL 체크
     */
    async sslCheck(websiteId) {
        try {
            const result = await this.client.post(`/websites/${websiteId}/ssl-check`);
            return result;
        } catch (error) {
            // 410 Gone 상태의 경우 특별 처리 (삭제된 웹사이트)
            if (error.status === 410) {
                console.warn(`삭제된 웹사이트에 대한 SSL 체크 요청: ${websiteId}`);
                this.client.showError('요청한 웹사이트가 삭제되어 SSL 체크를 수행할 수 없습니다');
            } else {
                this.client.handleError(error);
            }
            throw error;
        }
    }

    /**
     * 일괄 SSL 체크
     */
    async bulkCheck(data = {}) {
        try {
            const result = await this.client.post('/websites/batch-ssl-check', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 만료 임박 인증서 조회
     */
    async getExpiringCertificates(days = 30) {
        try {
            return await this.client.get('/websites/ssl/expiring', { days });
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * SSL 통계 조회
     */
    async getStatistics() {
        try {
            return await this.client.get('/websites/ssl/statistics');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }
}

/**
 * SSL API
 */
class SSLAPI {
    constructor(client) {
        this.client = client;
    }

    /**
     * SSL 상태 요약
     */
    async getStatusSummary(params = {}) {
        try {
            return await this.client.get('/ssl/status', params);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * SSL 인증서 목록
     */
    async getCertificates(params = {}) {
        try {
            return await this.client.get('/ssl/certificates', params);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * SSL 인증서 상세 조회
     */
    async getCertificate(certificateId) {
        try {
            return await this.client.get(`/ssl/certificates/${certificateId}`);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * SSL 히스토리 조회
     */
    async getHistory(websiteId, params = {}) {
        try {
            return await this.client.get(`/ssl/history/${websiteId}`, params);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 빠른 SSL 체크
     */
    async quickCheck(data) {
        try {
            const result = await this.client.post('/ssl/quick-check', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }
}

/**
 * 헬스체크 API
 */
class HealthAPI {
    constructor(client) {
        this.client = client;
    }

    /**
     * 전체 헬스체크
     */
    async getHealth() {
        try {
            return await this.client.get('/health');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 라이브니스 체크
     */
    async getLiveness() {
        try {
            return await this.client.get('/health/liveness');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 레디니스 체크
     */
    async getReadiness() {
        try {
            return await this.client.get('/health/readiness');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 메트릭 조회
     */
    async getMetrics() {
        try {
            return await this.client.get('/health/metrics');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 핑 테스트
     */
    async ping() {
        try {
            return await this.client.get('/health/ping');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 버전 정보
     */
    async getVersion() {
        try {
            return await this.client.get('/health/version');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }
}

/**
 * 작업 관리 API
 */
class TasksAPI {
    constructor(client) {
        this.client = client;
    }

    /**
     * 스케줄러 상태 조회
     */
    async getSchedulerStatus() {
        try {
            return await this.client.get('/tasks/scheduler/status');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 스케줄된 작업 수동 실행
     */
    async triggerScheduledJob(jobId) {
        try {
            const result = await this.client.post('/tasks/scheduler/trigger', { job_id: jobId });
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * SSL 체크 작업 제출
     */
    async submitSSLCheck(data = {}) {
        try {
            const result = await this.client.post('/tasks/background/ssl-check', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 알림 작업 제출
     */
    async submitNotification(data = {}) {
        try {
            const result = await this.client.post('/tasks/background/notifications', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 백그라운드 작업 목록 조회
     */
    async getBackgroundTasks(params = {}) {
        try {
            return await this.client.get('/tasks/background/tasks', params);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 백그라운드 작업 상세 조회
     */
    async getBackgroundTask(taskId) {
        try {
            return await this.client.get(`/tasks/background/tasks/${taskId}`);
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 실행기 통계 조회
     */
    async getExecutorStats() {
        try {
            return await this.client.get('/tasks/background/stats');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }
}

/**
 * 설정 관리 API
 */
class SettingsAPI {
    constructor(client) {
        this.client = client;
    }

    /**
     * 시스템 설정 조회
     */
    async get() {
        try {
            return await this.client.get('/settings');
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 시스템 설정 업데이트
     */
    async update(data) {
        try {
            const result = await this.client.put('/settings', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * Webhook 테스트
     */
    async testWebhook(webhookUrl = null) {
        try {
            const data = webhookUrl ? { webhook_url: webhookUrl } : {};
            const result = await this.client.post('/settings/test-webhook', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }

    /**
     * 특정 일수 기준 실제 데이터 알림 테스트
     */
    async testNotificationWithDays(days, webhookUrl = null) {
        try {
            const data = {
                days: days,
                webhook_url: webhookUrl || null
            };
            const result = await this.client.post('/settings/test-notification-with-days', data);
            return result;
        } catch (error) {
            this.client.handleError(error);
            throw error;
        }
    }
}

/**
 * 유틸리티 클래스
 */
class APIUtils {
    /**
     * URL 파라미터 생성
     */
    static buildQueryString(params) {
        const searchParams = new URLSearchParams();

        Object.keys(params).forEach(key => {
            const value = params[key];
            if (value !== null && value !== undefined) {
                if (Array.isArray(value)) {
                    value.forEach(item => searchParams.append(key, item));
                } else {
                    searchParams.append(key, value);
                }
            }
        });

        return searchParams.toString();
    }

    /**
     * 날짜 포맷팅
     */
    static formatDate(dateString, options = {}) {
        const date = new Date(dateString);
        const defaultOptions = {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            ...options
        };

        return date.toLocaleString('ko-KR', defaultOptions);
    }

    /**
     * 파일 크기 포맷팅
     */
    static formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';

        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));

        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * 만료일까지 남은 일수 계산
     */
    static calculateDaysUntilExpiry(expiryDate) {
        const now = new Date();
        const expiry = new Date(expiryDate);
        const diffTime = expiry - now;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

        return diffDays;
    }

    /**
     * SSL 상태에 따른 색상 클래스 반환
     */
    static getStatusColorClass(status) {
        const colorMap = {
            'valid': 'text-green-600 bg-green-100 border-green-200',
            'expired': 'text-red-600 bg-red-100 border-red-200',
            'invalid': 'text-yellow-600 bg-yellow-100 border-yellow-200',
            'unknown': 'text-gray-600 bg-gray-100 border-gray-200'
        };

        return colorMap[status] || colorMap['unknown'];
    }

    /**
     * 디바운스 함수
     */
    static debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * 쓰로틀 함수
     */
    static throttle(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }

    /**
     * 깊은 복사
     */
    static deepClone(obj) {
        if (obj === null || typeof obj !== 'object') return obj;
        if (obj instanceof Date) return new Date(obj.getTime());
        if (obj instanceof Array) return obj.map(item => APIUtils.deepClone(item));
        if (typeof obj === 'object') {
            const clonedObj = {};
            for (const key in obj) {
                if (obj.hasOwnProperty(key)) {
                    clonedObj[key] = APIUtils.deepClone(obj[key]);
                }
            }
            return clonedObj;
        }
    }

    /**
     * 로컬 스토리지 래퍼
     */
    static storage = {
        get(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(key);
                return item ? JSON.parse(item) : defaultValue;
            } catch (error) {
                console.error('localStorage get 오류:', error);
                return defaultValue;
            }
        },

        set(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
                return true;
            } catch (error) {
                console.error('localStorage set 오류:', error);
                return false;
            }
        },

        remove(key) {
            try {
                localStorage.removeItem(key);
                return true;
            } catch (error) {
                console.error('localStorage remove 오류:', error);
                return false;
            }
        },

        clear() {
            try {
                localStorage.clear();
                return true;
            } catch (error) {
                console.error('localStorage clear 오류:', error);
                return false;
            }
        }
    };
}

/**
 * 전역 API 인스턴스 생성
 */
window.SSLMonitorAPI = new SSLMonitorAPI();
window.APIUtils = APIUtils;

// 개발 모드에서 디버깅을 위한 전역 노출
if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    window.SSLMonitorAPIClass = SSLMonitorAPI;
    window.APIError = APIError;
}

// 모듈 export (ES6 모듈 환경에서 사용)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        SSLMonitorAPI,
        APIError,
        APIUtils
    };
}