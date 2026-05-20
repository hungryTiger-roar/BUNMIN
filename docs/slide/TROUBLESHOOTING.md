# Troubleshooting - 문제 해결 가이드

> 슬라이드 번역 파이프라인에서 발생하는 일반적인 문제와 해결 방법

---

## 목차

1. [CUDA / GPU 관련](#1-cuda--gpu-관련)
2. [번역 품질 문제](#2-번역-품질-문제)
3. [폰트 / 렌더링 문제](#3-폰트--렌더링-문제)
4. [파일 / 경로 문제](#4-파일--경로-문제)
5. [모델 로드 문제](#5-모델-로드-문제)
6. [성능 문제](#6-성능-문제)

---

## 1. CUDA / GPU 관련

### 1.1 CUDA out of memory

**증상:**
```
torch.cuda.OutOfMemoryError: CUDA out of memory
```

**원인:**
- VLM과 Surya가 동시에 GPU에 로드됨
- 이전 실행에서 GPU 메모리가 해제되지 않음

**해결:**
```bash
# 1. 서버 재시작
pkill -f uvicorn
uvicorn app.main:app --reload

# 2. 또는 Python에서 수동 메모리 정리
import gc
import torch
gc.collect()
torch.cuda.empty_cache()
torch.cuda.synchronize()
```

**예방:**
- Stage 전환 시 모델 언로드 확인
- `OCR_CHUNK_SIZE`를 줄여서 배치 크기 축소 (기본: 5)

---

### 1.2 CUDA not available

**증상:**
```
RuntimeError: CUDA is not available
```

**원인:**
- NVIDIA 드라이버 미설치
- PyTorch CUDA 버전 불일치

**해결:**
```bash
# CUDA 확인
nvidia-smi

# PyTorch CUDA 확인
python -c "import torch; print(torch.cuda.is_available())"

# PyTorch 재설치 (CUDA 12.1 예시)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

---

### 1.3 GPU 메모리 부족 (8GB 미만)

**증상:**
- 4GB VRAM에서 VLM 또는 Surya 로드 실패

**해결:**
```bash
# .env에 CPU 모드 설정
VLM_DEVICE=cpu
OCR_DEVICE=cpu
```

**참고:** CPU 모드는 속도가 매우 느려집니다 (10배 이상).

---

## 2. 번역 품질 문제

### 2.1 특정 용어가 잘못 번역됨

**증상:**
- "한계비용"이 "limit cost"로 번역됨 (올바른 번역: "Marginal Cost")

**해결:**
```bash
# config/glossary.csv에 용어 추가
echo "한계비용,Marginal Cost" >> config/glossary.csv
```

**주의:**
- 2글자 이상만 등록 가능
- 파일 수정 후 서버 재시작 불필요 (자동 리로드)

---

### 2.2 숫자가 번역에서 누락됨

**증상:**
- "경제학의 10대 기본원리" → "Economic Principles" (10 누락)

**해결:**
```bash
# CSV에 해당 패턴 추가
echo "10대 기본원리,10 Fundamental Principles" >> config/glossary.csv
echo "10대 원리,10 Principles" >> config/glossary.csv
```

---

### 2.3 번역이 "???" 또는 빈 문자열

**증상:**
- 일부 블록이 "???"로 번역됨
- translations.json에 빈 translated 필드

**원인:**
- VLM이 해당 텍스트를 처리하지 못함
- 입력 텍스트가 너무 길거나 복잡함

**해결:**
1. 로그 확인:
   ```bash
   cat uploads/translated/pdf_layer_pipeline.log | grep "RETRY\|WARN"
   ```

2. 해당 블록 수동 확인:
   ```bash
   cat uploads/translated/source_texts.json | jq '.[] | select(.block_id == "p3_b2")'
   ```

3. CSV에 해당 문구 추가

---

### 2.4 한글이 일부 남아있음

**증상:**
- 번역된 PDF에서 원본 한글 일부가 보임
- 특히 prefix (bullet) 영역

**원인:**
- Redaction bbox가 원본 텍스트를 완전히 덮지 못함
- `keep_prefix=True`인 경우 prefix 영역 미처리

**해결:**
- [fix-korean-remnants-bug.md](./fix-korean-remnants-bug.md) 참고
- `pdf_text_replacer.py`에서 padding 값 조정

---

## 3. 폰트 / 렌더링 문제

### 3.1 폰트를 찾을 수 없음

**증상:**
```
FileNotFoundError: Font file not found: C:/Windows/Fonts/malgun.ttf
```

**해결 (Windows):**
```bash
# .env
KOREAN_FONT_PATH=C:/Windows/Fonts/malgun.ttf
```

**해결 (Linux):**
```bash
# 나눔 폰트 설치
sudo apt-get install fonts-nanum

# .env
KOREAN_FONT_PATH=/usr/share/fonts/truetype/nanum/NanumGothic.ttf
```

**해결 (Mac):**
```bash
# .env
KOREAN_FONT_PATH=/System/Library/Fonts/AppleSDGothicNeo.ttc
```

---

### 3.2 영어 텍스트가 안 보임

**증상:**
- 번역된 PDF에서 텍스트가 배경색과 같아서 안 보임

**원인:**
- 텍스트 색상과 배경색의 대비 부족

**해결:**
- `pdf_text_replacer.py`의 `_ensure_contrast()` 함수 확인
- 대비 임계값 조정 (기본: 0.3)

---

### 3.3 텍스트가 bbox를 넘어감

**증상:**
- 번역된 텍스트가 원본 영역을 벗어남

**해결:**
- `expand_allowed=True` 확인
- 폰트 크기 자동 조절 로직 확인 (`pdf_text_replacer.py`)

---

## 4. 파일 / 경로 문제

### 4.1 PDF 파일을 찾을 수 없음

**증상:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'uploads/slides/xxx.pdf'
```

**해결:**
```bash
# uploads 디렉토리 생성
mkdir -p uploads/slides uploads/translated uploads/cache
```

---

### 4.2 권한 오류

**증상:**
```
PermissionError: [Errno 13] Permission denied
```

**해결:**
```bash
# Linux/Mac
chmod -R 755 uploads/

# Windows (관리자 권한으로 실행)
```

---

### 4.3 glossary.csv 로드 안 됨

**증상:**
- 로그에 `[TermCorrections] CSV 파일 없음` 출력
- 용어집이 적용되지 않음

**해결:**
```bash
# CSV 파일 위치 확인
ls -la config/glossary.csv

# 또는 환경변수로 경로 지정
export GLOSSARY_FILE=/path/to/glossary.csv
```

---

## 5. 모델 로드 문제

### 5.1 VLM 모델 다운로드 실패

**증상:**
```
OSError: Can't load tokenizer for 'Qwen/Qwen3-VL-4B-Instruct'
```

**해결:**
```bash
# HuggingFace 로그인
huggingface-cli login

# 또는 수동 다운로드
git lfs install
git clone https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct models/Qwen3-VL-4B-Instruct
```

---

### 5.2 Surya 모델 로드 실패

**증상:**
```
RuntimeError: Error loading Surya model
```

**해결:**
```bash
# Surya 재설치
pip uninstall surya-ocr
pip install surya-ocr

# 캐시 삭제 후 재시도
rm -rf ~/.cache/surya
```

---

### 5.3 bitsandbytes 오류 (Windows)

**증상:**
```
ImportError: bitsandbytes is not available
```

**해결:**
```bash
# Windows용 bitsandbytes 설치
pip install bitsandbytes-windows

# 또는 CPU 모드 사용
# .env
VLM_QUANTIZATION=none
VLM_DEVICE=cpu
```

---

## 6. 성능 문제

### 6.1 번역이 너무 느림

**증상:**
- 페이지당 30초 이상 소요

**원인:**
- CPU 모드로 실행 중
- 모델이 매 페이지마다 로드됨

**해결:**
1. GPU 사용 확인:
   ```bash
   nvidia-smi
   ```

2. Stage 배치 확인 (로그에서):
   ```
   [Stage 3] Surya 로드 (1회) → Page 1~10 OCR
   [Stage 4] VLM 로드 (1회) → Page 1~10 번역
   ```

3. 배치 크기 조정:
   ```bash
   # .env
   OCR_CHUNK_SIZE=10  # 기본 5
   ```

---

### 6.2 메모리 사용량 계속 증가

**증상:**
- 여러 PDF 처리 후 메모리 누수

**해결:**
```bash
# 캐시 정리 API 호출
curl -X POST http://localhost:8000/slides/clear-cache

# 또는 Python에서
from app.services.slide_translation import clear_cache
clear_cache()
```

---

## 디버깅 팁

### 로그 레벨 변경

```python
# app/main.py 또는 slides.py
import logging
logging.getLogger("slide_translation").setLevel(logging.DEBUG)
```

### 중간 결과 확인

```bash
# 원본 텍스트
cat uploads/translated/source_texts.json | jq '.'

# 번역 결과
cat uploads/translated/translations.json | jq '.'

# 파이프라인 로그
cat uploads/translated/pdf_layer_pipeline.log
```

### 특정 블록 디버깅

```bash
# 특정 블록만 필터링
cat uploads/translated/translations.json | jq '.[] | select(.block_id == "p1_b0")'
```

---

## 도움 요청

위 해결책으로 해결되지 않는 경우:

1. 로그 파일 첨부: `uploads/translated/pdf_layer_pipeline.log`
2. 환경 정보: `pip list | grep -E "torch|transformers|surya"`
3. GPU 정보: `nvidia-smi`
4. 재현 가능한 PDF 샘플

---

## 관련 문서

- [QUICK_START.md](./QUICK_START.md) - 빠른 시작 가이드
- [PIPELINE_FLOW.md](./PIPELINE_FLOW.md) - 파이프라인 흐름
- [fix-korean-remnants-bug.md](./fix-korean-remnants-bug.md) - 한글 잔상 버그 수정
