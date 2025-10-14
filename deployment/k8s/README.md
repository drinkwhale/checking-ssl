# Kubernetes 배포 가이드

SSL Certificate Monitoring Dashboard를 Kubernetes 클러스터에 배포하는 가이드입니다.

## 사전 준비

### 1. Docker 이미지 빌드

```bash
# 프로젝트 루트에서 실행
cd /path/to/cheking-ssl
docker build -t ssl-monitoring:latest -f deployment/k8s/Dockerfile .
```

**참고**: 빌드 컨텍스트는 프로젝트 루트(`.`)이며, Dockerfile은 `deployment/k8s/Dockerfile`을 사용합니다.

### 2. Docker 이미지 레지스트리에 푸시 (선택사항)

```bash
# Docker Hub 사용 예시
docker tag ssl-monitoring:latest your-dockerhub-username/ssl-monitoring:latest
docker push your-dockerhub-username/ssl-monitoring:latest

# 또는 프라이빗 레지스트리 사용
docker tag ssl-monitoring:latest your-registry.com/ssl-monitoring:latest
docker push your-registry.com/ssl-monitoring:latest
```

**주의**: `deployment.yaml`에서 `image` 필드를 실제 이미지 이름으로 수정해야 합니다.

## 배포 방법

### 1. PostgreSQL Secret 설정

```bash
# PostgreSQL secret 파일 생성
cp deployment/k8s/postgresql-secret.yaml.example deployment/k8s/postgresql-secret.yaml

# PostgreSQL 비밀번호 수정
vim deployment/k8s/postgresql-secret.yaml

# Secret 생성
kubectl apply -f deployment/k8s/postgresql-secret.yaml
```

### 2. PostgreSQL PVC 및 Deployment 배포

```bash
# PersistentVolumeClaim 생성
kubectl apply -f deployment/k8s/postgresql-pvc.yaml

# PostgreSQL Deployment 및 Service 생성
kubectl apply -f deployment/k8s/postgresql-deployment.yaml

# PostgreSQL Pod 상태 확인
kubectl get pods -l app=postgresql
kubectl logs -l app=postgresql
```

### 3. 애플리케이션 Secret 설정

```bash
# secret.yaml.example 파일을 복사하여 실제 값 입력
cp deployment/k8s/secret.yaml.example deployment/k8s/secret.yaml

# secret.yaml 파일 편집
# database-url을 다음과 같이 설정:
# postgresql+asyncpg://ssl_monitor_user:your-password@postgresql:5432/ssl_monitoring
vim deployment/k8s/secret.yaml

# Secret 생성
kubectl apply -f deployment/k8s/secret.yaml
```

### 4. 애플리케이션 Deployment 생성

```bash
kubectl apply -f deployment/k8s/deployment.yaml
```

### 5. Service 생성

```bash
kubectl apply -f deployment/k8s/service.yaml
```

### 6. Ingress 설정 (외부 접근용)

```bash
# ingress.yaml 파일에서 도메인 수정
vim deployment/k8s/ingress.yaml

# Ingress 생성
kubectl apply -f deployment/k8s/ingress.yaml

# Ingress 상태 확인
kubectl get ingress ssl-monitoring-ingress
kubectl describe ingress ssl-monitoring-ingress
```

### 7. 배포 상태 확인

```bash
# 모든 리소스 상태 확인
kubectl get all

# PostgreSQL Pod 상태 확인
kubectl get pods -l app=postgresql
kubectl logs -l app=postgresql

# 애플리케이션 Pod 상태 확인
kubectl get pods -l app=ssl-monitoring
kubectl logs -l app=ssl-monitoring --tail=100 -f

# Deployment 상태 확인
kubectl get deployment ssl-monitoring
kubectl get deployment postgresql

# Service 상태 확인
kubectl get service ssl-monitoring
kubectl get service postgresql

# Ingress 상태 확인
kubectl get ingress ssl-monitoring-ingress

# PVC 상태 확인
kubectl get pvc postgres-pvc
```

## 리소스 구성

### Deployment (`deployment.yaml`)

- **replicas**: 2개의 Pod 실행 (고가용성)
- **컨테이너 포트**: 8080
- **환경 변수**:
  - `DATABASE_URL`: PostgreSQL 연결 문자열 (Secret에서 주입)
  - `TEAMS_WEBHOOK_URL`: Teams 웹훅 URL (Secret에서 주입, 선택사항)
  - `SSL_TIMEOUT_SECONDS`: SSL 체크 타임아웃 (기본: 10초)
  - `MAX_CONCURRENT_CHECKS`: 동시 SSL 체크 수 (기본: 5개)

- **리소스 제한**:
  - **requests**: CPU 250m, Memory 256Mi
  - **limits**: CPU 500m, Memory 512Mi

- **헬스 체크**:
  - **livenessProbe**: Pod가 정상 동작 중인지 확인
  - **readinessProbe**: Pod가 트래픽을 받을 준비가 되었는지 확인
  - **startupProbe**: 초기 구동 시간을 고려한 체크

### Service (`service.yaml`)

- **타입**: ClusterIP (클러스터 내부에서만 접근 가능)
- **포트 매핑**: 80 (외부) → 8080 (컨테이너)
- **selector**: `app=ssl-monitoring` 레이블을 가진 Pod에 트래픽 전달

### PostgreSQL Deployment (`postgresql-deployment.yaml`)

- **replicas**: 1개 (단일 인스턴스)
- **컨테이너 포트**: 5432
- **이미지**: postgres:15-alpine
- **환경 변수**:
  - `POSTGRES_DB`: ssl_monitoring (데이터베이스 이름)
  - `POSTGRES_USER`: Secret에서 주입
  - `POSTGRES_PASSWORD`: Secret에서 주입
- **스토리지**: 10Gi PersistentVolumeClaim
- **리소스 제한**:
  - **requests**: CPU 250m, Memory 256Mi
  - **limits**: CPU 500m, Memory 512Mi

### Ingress (`ingress.yaml`)

- **ingressClassName**: nginx (NGINX Ingress Controller 사용)
- **호스트**: ssl-monitoring.example.com (실제 도메인으로 변경 필요)
- **TLS**: 인증서 Secret 설정 (cert-manager 사용 권장)
- **annotations**:
  - SSL 리다이렉트 활성화
  - 프록시 타임아웃 설정
  - CORS 설정 (주석 처리됨, 필요시 활성화)

## 데이터베이스 연결 설정

애플리케이션은 다음 형식의 DATABASE_URL을 사용합니다:

```
postgresql+asyncpg://username:password@postgresql:5432/ssl_monitoring
```

**중요 포인트**:
- 호스트명은 `postgresql` (Kubernetes Service 이름)
- 포트는 `5432` (PostgreSQL 기본 포트)
- 데이터베이스명은 `ssl_monitoring`
- username과 password는 `postgresql-secrets`에서 설정

## 외부 접근 설정

### Ingress 사용 (권장)

이미 `ingress.yaml` 파일이 제공됩니다. 다음 사항을 수정하세요:

1. **도메인 설정**: `ssl-monitoring.example.com`을 실제 도메인으로 변경
2. **Ingress Controller 설치** (NGINX 예시):
```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml
```

3. **TLS 인증서 설정** (cert-manager 사용 시):
```bash
# cert-manager 설치
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# ClusterIssuer 생성 (Let's Encrypt)
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF
```

4. **DNS 설정**: 도메인의 A 레코드를 Ingress Controller의 외부 IP로 설정
```bash
# Ingress Controller의 외부 IP 확인
kubectl get svc -n ingress-nginx
```

### Option 2: LoadBalancer 타입으로 변경

`service.yaml`에서 `type: ClusterIP`를 `type: LoadBalancer`로 변경:

```yaml
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8080
```

### Option 3: NodePort 타입으로 변경

```yaml
spec:
  type: NodePort
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080  # 30000-32767 범위의 포트
```

## 스케일링

```bash
# Pod 수 조정 (예: 3개로 증가)
kubectl scale deployment ssl-monitoring --replicas=3

# 또는 deployment.yaml 파일 수정 후
kubectl apply -f deployment/k8s/deployment.yaml
```

## 업데이트 및 롤백

```bash
# 새 이미지로 업데이트
kubectl set image deployment/ssl-monitoring ssl-monitoring=ssl-monitoring:v2

# 롤아웃 상태 확인
kubectl rollout status deployment/ssl-monitoring

# 롤백
kubectl rollout undo deployment/ssl-monitoring

# 특정 리비전으로 롤백
kubectl rollout undo deployment/ssl-monitoring --to-revision=2

# 롤아웃 히스토리 확인
kubectl rollout history deployment/ssl-monitoring
```

## 문제 해결

### Pod가 시작되지 않는 경우

```bash
# Pod 상세 정보 확인
kubectl describe pod -l app=ssl-monitoring

# Pod 로그 확인
kubectl logs -l app=ssl-monitoring --tail=100

# 이벤트 확인
kubectl get events --sort-by=.metadata.creationTimestamp
```

### 데이터베이스 연결 실패

1. Secret이 올바르게 생성되었는지 확인:
   ```bash
   kubectl get secret ssl-monitoring-secrets
   kubectl describe secret ssl-monitoring-secrets
   ```

2. 데이터베이스가 클러스터 내에서 접근 가능한지 확인

3. `DATABASE_URL` 형식 확인:
   - PostgreSQL: `postgresql+asyncpg://user:password@host:port/database`
   - SQLite는 프로덕션 환경에서 권장하지 않음

### 헬스 체크 실패

```bash
# Pod 내부에서 직접 헬스 체크 엔드포인트 테스트
kubectl exec -it <pod-name> -- curl http://localhost:8080/health
```

## 리소스 정리

```bash
# 모든 리소스 삭제
kubectl delete -f deployment/k8s/service.yaml
kubectl delete -f deployment/k8s/deployment.yaml
kubectl delete -f deployment/k8s/secret.yaml
```

## 참고사항

- **데이터베이스**: PostgreSQL을 사용하는 것을 권장합니다. 클러스터 내에 PostgreSQL을 배포하거나 외부 관리형 데이터베이스를 사용할 수 있습니다.
- **Persistent Volume**: 데이터베이스로 SQLite를 사용하는 경우 PersistentVolumeClaim을 설정해야 합니다.
- **보안**: Secret 파일은 절대 Git에 커밋하지 마세요. `.gitignore`에 `secret.yaml` 추가를 권장합니다.
- **모니터링**: Prometheus, Grafana 등과 연동하여 애플리케이션 모니터링을 설정하는 것을 권장합니다.
