"""
슬라이드 번역 API 엔드포인트
"""

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
import sys

# translate_slide_v3 모듈 경로 추가 (teamRepo 디렉토리)
_REPO_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_REPO_DIR))

router = APIRouter(prefix="/translate", tags=["translate"])

# 임시 파일 저장 경로
TEMP_DIR = Path(tempfile.gettempdir()) / "slide_translate"
TEMP_DIR.mkdir(exist_ok=True)


@router.post("/slide")
async def translate_slide_api(file: UploadFile = File(...)):
    """
    슬라이드 이미지 번역 API

    Args:
        file: 업로드할 이미지 파일 (PNG, JPG)

    Returns:
        번역된 이미지 파일
    """
    # 파일 확장자 확인
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {allowed_extensions}"
        )

    # 임시 파일 저장
    file_id = str(uuid.uuid4())
    input_path = TEMP_DIR / f"{file_id}_input{file_ext}"
    output_path = TEMP_DIR / f"{file_id}_output{file_ext}"

    try:
        # 업로드 파일 저장
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)

        # 번역 실행
        from translate_slide_v3 import translate_slide
        result = translate_slide(str(input_path), str(output_path))

        if not result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"번역 실패: {result.get('error', 'Unknown error')}"
            )

        # 번역된 이미지 반환
        return FileResponse(
            path=str(output_path),
            media_type=f"image/{file_ext[1:]}",
            filename=f"translated_{file.filename}"
        )

    finally:
        # 입력 파일 정리 (출력 파일은 응답 후 자동 정리)
        if input_path.exists():
            os.remove(input_path)


@router.post("/slide/json")
async def translate_slide_json_api(file: UploadFile = File(...)):
    """
    슬라이드 이미지 번역 API (JSON 응답)

    Args:
        file: 업로드할 이미지 파일

    Returns:
        번역 결과 JSON (regions 포함)
    """
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다."
        )

    file_id = str(uuid.uuid4())
    input_path = TEMP_DIR / f"{file_id}_input{file_ext}"
    output_path = TEMP_DIR / f"{file_id}_output{file_ext}"

    try:
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)

        from translate_slide_v3 import translate_slide
        result = translate_slide(str(input_path), str(output_path))

        if not result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"번역 실패: {result.get('error', 'Unknown error')}"
            )

        # JSON 응답 (이미지는 base64로 인코딩)
        import base64
        with open(output_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode()

        return {
            "success": True,
            "filename": file.filename,
            "regions": [
                {
                    "korean": r["ocr_text"],
                    "english": r.get("english", r["ocr_text"]),
                    "bbox": r["bbox"],
                    "skipped": r.get("skip_translate", False)
                }
                for r in result["regions"]
            ],
            "image_base64": image_base64,
            "image_type": file_ext[1:]
        }

    finally:
        if input_path.exists():
            os.remove(input_path)
        if output_path.exists():
            os.remove(output_path)
