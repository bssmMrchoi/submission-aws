"""submission-aws 백엔드: 강좌 개설 + 과제 업로드 (FastAPI 한 파일)

.env 가 없어도 실행된다.
- DB_HOST 가 비어 있으면 로컬 SQLite(local.db)를 쓴다.
- S3_BUCKET 이 비어 있으면 업로드/다운로드만 막고 안내 메시지를 돌려준다.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import ForeignKey, String, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

load_dotenv()  # .env 가 없으면 아무 일도 하지 않음


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


MAX_UPLOAD_MB = 20
KST = timezone(timedelta(hours=9))

DB_ERROR = "DB 연결 실패: .env의 DB 설정과 RDS 보안 그룹을 확인하세요."
S3_NOT_SET = "S3가 연결되지 않았습니다. 업로드하려면 .env에 S3_BUCKET을 먼저 설정하세요."
S3_NO_CREDENTIALS = "S3 자격 증명이 없습니다. EC2에 IAM 역할을 연결하거나 .env에 액세스 키를 입력하세요."


# ---------- DB ----------
DB_HOST = env("DB_HOST")

if DB_HOST:
    db_url = URL.create(
        "mysql+pymysql",
        username=env("DB_USER", "admin"),
        password=env("DB_PASSWORD"),
        host=DB_HOST,
        port=int(env("DB_PORT", "3306")),
        database=env("DB_NAME", "submission"),
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600,
                           connect_args={"connect_timeout": 5})
else:
    engine = create_engine("sqlite:///./local.db", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(engine)


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "course"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now_kst)


class Submission(Base):
    __tablename__ = "submission"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"))
    student_name: Mapped[str] = mapped_column(String(50))
    filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now_kst)


tables_ready = False


def ensure_tables():
    """테이블이 없으면 만든다. RDS를 나중에 고쳐도 재시작 없이 동작하도록 요청마다 확인."""
    global tables_ready
    if not tables_ready:
        Base.metadata.create_all(engine)
        tables_ready = True


def get_db():
    ensure_tables()
    with SessionLocal() as db:
        yield db


# ---------- S3 ----------
S3_BUCKET = env("S3_BUCKET")
s3 = None

if S3_BUCKET:
    s3_options = {"region_name": env("AWS_REGION", "ap-northeast-2"),
                  "config": Config(signature_version="s3v4")}
    # 키가 둘 다 있으면 그 키를 쓰고, 없으면 boto3 기본 체인(EC2 IAM 역할, aws configure)을 쓴다
    if env("AWS_ACCESS_KEY_ID") and env("AWS_SECRET_ACCESS_KEY"):
        s3_options["aws_access_key_id"] = env("AWS_ACCESS_KEY_ID")
        s3_options["aws_secret_access_key"] = env("AWS_SECRET_ACCESS_KEY")
    s3 = boto3.client("s3", **s3_options)


def require_s3():
    if s3 is None:
        raise HTTPException(503, S3_NOT_SET)


def s3_error(e: Exception) -> HTTPException:
    if isinstance(e, NoCredentialsError):
        return HTTPException(503, S3_NO_CREDENTIALS)
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        return HTTPException(503, f"S3 업로드 실패: 버킷 이름과 IAM 권한을 확인하세요. ({code})")
    return HTTPException(503, f"S3 오류: {e}")


# ---------- 앱 ----------
try:
    ensure_tables()
except SQLAlchemyError as e:
    print(f"[경고] {DB_ERROR} ({e.__class__.__name__}) - 서버는 계속 실행합니다.")

app = FastAPI(title="submission-aws")


@app.exception_handler(SQLAlchemyError)
def db_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"detail": DB_ERROR})


def course_dict(c: Course) -> dict:
    return {"id": c.id, "title": c.title, "description": c.description, "created_at": fmt(c.created_at)}


def submission_dict(s: Submission) -> dict:
    return {"id": s.id, "student_name": s.student_name, "filename": s.filename,
            "created_at": fmt(s.created_at)}


@app.get("/api/health")
def health():
    """ALB 헬스 체크용. DB·S3 상태와 상관없이 항상 ok."""
    return {"status": "ok"}


@app.get("/api/status")
def status():
    if DB_HOST:
        try:
            ensure_tables()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db = {"type": "rds", "ok": True, "message": f"RDS 연결됨 ({DB_HOST})"}
        except SQLAlchemyError:
            db = {"type": "rds", "ok": False, "message": DB_ERROR}
    else:
        db = {"type": "sqlite", "ok": True, "message": "로컬 SQLite 사용 중 (.env에 RDS 설정 전)"}

    if s3:
        s3_status = {"configured": True, "bucket": S3_BUCKET, "message": f"S3 버킷 연결됨 ({S3_BUCKET})"}
    else:
        s3_status = {"configured": False, "bucket": None, "message": S3_NOT_SET}

    return {"db": db, "s3": s3_status}


class CourseIn(BaseModel):
    title: str
    description: str | None = None


@app.get("/api/courses")
def list_courses(db: Session = Depends(get_db)):
    courses = db.scalars(select(Course).order_by(Course.id.desc())).all()
    return [course_dict(c) for c in courses]


@app.post("/api/courses", status_code=201)
def create_course(body: CourseIn, db: Session = Depends(get_db)):
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "강좌명을 입력하세요.")
    course = Course(title=title, description=(body.description or "").strip() or None)
    db.add(course)
    db.commit()
    return course_dict(course)


@app.get("/api/courses/{course_id}/submissions")
def list_submissions(course_id: int, db: Session = Depends(get_db)):
    if db.get(Course, course_id) is None:
        raise HTTPException(404, "강좌를 찾을 수 없습니다.")
    subs = db.scalars(
        select(Submission).where(Submission.course_id == course_id).order_by(Submission.id.desc())
    ).all()
    return [submission_dict(s) for s in subs]


@app.post("/api/courses/{course_id}/submissions", status_code=201)
def upload_submission(
    course_id: int,
    student_name: str = Form(""),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    if db.get(Course, course_id) is None:
        raise HTTPException(404, "강좌를 찾을 수 없습니다.")
    student_name = student_name.strip()
    if not student_name or file is None or not file.filename:
        raise HTTPException(400, "이름과 파일을 모두 입력하세요.")
    require_s3()
    if (file.size or 0) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"파일은 {MAX_UPLOAD_MB}MB 이하만 올릴 수 있습니다.")

    key = f"courses/{course_id}/{uuid.uuid4().hex}_{file.filename}"
    try:
        extra = {"ContentType": file.content_type} if file.content_type else None
        s3.upload_fileobj(file.file, S3_BUCKET, key, ExtraArgs=extra)
    except (BotoCoreError, ClientError) as e:
        raise s3_error(e)

    # S3 업로드가 성공한 뒤에만 DB에 기록
    sub = Submission(course_id=course_id, student_name=student_name, filename=file.filename, s3_key=key)
    db.add(sub)
    db.commit()
    return submission_dict(sub)


@app.get("/api/submissions/{sub_id}/download")
def download(sub_id: int, db: Session = Depends(get_db)):
    sub = db.get(Submission, sub_id)
    if sub is None:
        raise HTTPException(404, "제출 기록을 찾을 수 없습니다.")
    require_s3()
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": sub.s3_key,
                "ResponseContentDisposition": f"attachment; filename*=UTF-8''{quote(sub.filename)}",
            },
            ExpiresIn=300,
        )
    except (BotoCoreError, ClientError) as e:
        raise s3_error(e)
    return RedirectResponse(url, status_code=302)
