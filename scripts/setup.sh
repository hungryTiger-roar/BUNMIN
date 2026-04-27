#!/usr/bin/env bash
set -e

echo "========================================"
echo "  Aunion AI 환경 설정"
echo "========================================"

# ─── 1. 루트 npm 패키지 (concurrently, wait-on 등) ───────────────────────────
echo ""
echo "[1/6] 루트 npm 패키지 설치..."
npm install
echo "  완료"

# ─── 2. 프론트엔드 npm 패키지 ─────────────────────────────────────────────────
echo ""
echo "[2/6] 프론트엔드 npm 패키지 설치..."
npm install --prefix frontend
echo "  완료"

# ─── 3. .env 파일 ─────────────────────────────────────────────────────────────
echo ""
echo "[3/6] 환경 설정 파일 확인..."
if [ -f .env ]; then
    echo "  .env 이미 존재 → 스킵"
else
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "  .env 생성 완료 (.env.example 복사)"
        echo "  ⚠️  .env 파일을 열어 HF_TOKEN과 PYTHON_PATH를 설정해주세요."
    else
        echo "  ⚠️  .env.example 없음 — .env를 수동으로 만들어주세요."
    fi
fi

# ─── 4. conda aunion 환경 ─────────────────────────────────────────────────────
echo ""
echo "[4/6] conda 환경 확인..."
if conda env list | grep -q "^aunion"; then
    echo "  aunion 환경 이미 존재 → 스킵"
else
    echo "  aunion 환경 생성 중 (Python 3.11)..."
    conda create -n aunion python=3.11 -y
    echo "  완료"
fi

# ─── 5. Python 패키지 ─────────────────────────────────────────────────────────
echo ""
echo "[5/6] Python 패키지 설치..."

# requirements.txt (이미 설치된 버전은 자동 스킵)
conda run --no-capture-output -n aunion pip install -r backend/requirements.txt

# torch: CUDA 빌드가 이미 있으면 스킵
if conda run --no-capture-output -n aunion python -c \
    "import torch; assert 'cu' in torch.__version__" 2>/dev/null; then
    echo "  torch CUDA 버전 이미 설치됨 → 스킵"
else
    echo "  torch CUDA 버전 설치 중 (cu126)..."
    conda run --no-capture-output -n aunion pip install \
        torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu126
fi

# numpy / Pillow 버전 고정 (이미 범위 안이면 자동 스킵)
conda run --no-capture-output -n aunion pip install \
    "numpy>=1.24.0,<2.0.0" "Pillow>=10.2.0,<11.0.0"

echo "  완료"

# ─── 6. AI 모델 다운로드 (이미 있으면 스크립트 내부에서 스킵) ──────────────────
echo ""
echo "[6/6] AI 모델 다운로드..."
conda run --no-capture-output -n aunion python scripts/download_models.py

# ─── 완료 ─────────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Setup 완료!"
echo "  npm run dev 로 서버를 시작하세요."
echo "========================================"
