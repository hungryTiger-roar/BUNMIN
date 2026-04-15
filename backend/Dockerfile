# Aunion AI Backend Dockerfile
# CPU 버전

FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY app/ ./app/

# 업로드 디렉토리 생성
RUN mkdir -p uploads/slides

# TTS 모델 디렉토리 생성
RUN mkdir -p models/piper

# 환경 변수
ENV PYTHONUNBUFFERED=1
ENV USE_GPU=false

# 포트 노출
EXPOSE 8000

# 실행
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
