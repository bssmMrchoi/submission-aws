# submission-aws

AWS 구축 수업용 과제 제출 미니 프로젝트. 관리자가 강좌를 개설하고, 학생이 강좌에 과제 파일을 업로드한다.
코드는 완성된 상태이며, **`.env` 작성만으로** RDS·S3에 연결한다.

```
브라우저 ─▶ Route 53 ─▶ CloudFront ─┬─ /*     ─▶ S3 (React 빌드 파일)
                                    └─ /api/* ─▶ ALB ─▶ EC2 (FastAPI) ─┬─▶ RDS (MySQL)
                                                                       └─▶ S3 (과제 파일)
```

## 로컬 실행

`.env` 없이도 바로 실행된다. (DB는 로컬 SQLite, S3는 미연결 상태 → 업로드만 막히고 안내 표시)

**백엔드** (Python 3.11 이상)
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
API 문서: http://localhost:8000/docs

**프론트엔드** (Node.js 20 이상, 다른 터미널에서)
```bash
cd frontend
npm install
npm run dev
```
화면: http://localhost:5173 (위쪽 상태줄에서 DB·S3 연결 상태 확인)

## 환경 설정 (`backend/.env`)

```bash
cd backend
cp .env.example .env              # Windows: copy .env.example .env
```

| 항목 | 설명 | 비워 두면 |
|---|---|---|
| `DB_HOST` | RDS 엔드포인트 | 로컬 SQLite(`backend/local.db`) 사용 |
| `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | RDS 포트, 초기 DB 이름, 마스터 사용자·암호 | - |
| `AWS_REGION` | 리전 (기본 `ap-northeast-2`) | - |
| `S3_BUCKET` | 과제 파일 버킷 이름 | 업로드·다운로드 막힘 + 안내 메시지 |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | 로컬 테스트용 IAM 사용자 키 | IAM 역할 / `aws configure` 사용 (EC2는 비워 두기) |

`.env`를 바꾼 뒤에는 백엔드를 다시 시작한다. `.env`는 GitHub에 올리지 않는다.

## 배포 요약

| 구분 | 어디서 | 방법 |
|---|---|---|
| 백엔드 | EC2 | `git clone` → `backend/`에서 `.env` 작성 → systemd로 uvicorn 실행 (포트 8000) |
| 프론트엔드 | 로컬 PC | `npm run build` → `dist/` **안의 파일들**을 S3 프론트 버킷 루트에 업로드 → CloudFront 무효화 `/*` |

EC2 서비스 등록 예시 (`/etc/systemd/system/submission.service`)
```ini
[Unit]
Description=submission api
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/submission-aws/backend
ExecStart=/home/ec2-user/submission-aws/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
Restart=always

[Install]
WantedBy=multi-user.target
```
