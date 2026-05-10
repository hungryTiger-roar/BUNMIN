"""
PDF 레이어 기반 번역 파이프라인

PDF 텍스트 레이어를 직접 수정하여 한글 → 영어 변환
이미지 기반 방식보다 품질이 높고 벡터 텍스트 유지
"""
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from .pdf_text_extractor import (
    check_pdf_has_text_layer,
    extract_korean_texts_for_translation,
)
from .pdf_text_replacer import replace_texts_in_pdf
from .llm_client import get_default_llm_client, BaseLLMClient

logger = logging.getLogger(__name__)


class PDFLayerPipeline:
    """PDF 레이어 기반 번역 파이프라인"""

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        output_dir: Optional[str] = None,
    ):
        self.llm_client = llm_client or get_default_llm_client()
        self.output_dir = output_dir
        self.log_lines = []

    def _log(self, message: str):
        """파이프라인 로그"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] {message}"
        self.log_lines.append(log_line)
        logger.info(message)
        print(log_line)

    def run(
        self,
        pdf_path: str,
        output_path: Optional[str] = None,
        target_lang: str = "en",
    ) -> dict:
        """
        PDF 번역 실행

        Args:
            pdf_path: 원본 PDF 경로
            output_path: 출력 PDF 경로 (없으면 자동 생성)
            target_lang: 목표 언어 (기본: en)

        Returns:
            {
                "success": bool,
                "output_path": str,
                "total_blocks": int,
                "translated_blocks": int,
                "failed_blocks": int,
                "details": [...]
            }
        """
        self._log("=" * 60)
        self._log("PDF Layer Translation Pipeline")
        self._log(f"Input: {pdf_path}")
        self._log("=" * 60)

        # 출력 경로 설정
        if not output_path:
            pdf_name = Path(pdf_path).stem
            output_dir = self.output_dir or Path(pdf_path).parent
            output_path = str(Path(output_dir) / f"{pdf_name}_translated.pdf")

        result = {
            "success": False,
            "output_path": output_path,
            "total_blocks": 0,
            "translated_blocks": 0,
            "failed_blocks": 0,
            "details": [],
        }

        try:
            # Step 1: PDF 텍스트 레이어 확인
            self._log("[Step 1] Checking PDF text layer...")
            layer_info = check_pdf_has_text_layer(pdf_path)
            self._log(f"  - Total pages: {layer_info['total_pages']}")
            self._log(f"  - Pages with text: {layer_info['pages_with_text']}")
            self._log(f"  - Korean blocks: {layer_info['korean_blocks']}")
            self._log(f"  - Recommendation: {layer_info['recommendation']}")

            if not layer_info["has_text_layer"]:
                self._log("  [WARN] No text layer found. OCR fallback needed.")
                result["error"] = "No text layer in PDF"
                return result

            # Step 2: 한글 텍스트 추출
            self._log("[Step 2] Extracting Korean texts...")
            korean_texts = extract_korean_texts_for_translation(pdf_path)
            result["total_blocks"] = len(korean_texts)
            self._log(f"  - Found {len(korean_texts)} Korean text blocks")

            if not korean_texts:
                self._log("  [INFO] No Korean text found.")
                result["success"] = True
                result["message"] = "No Korean text to translate"
                return result

            # Step 3: 번역
            self._log("[Step 3] Translating texts...")
            translations = self._translate_texts(korean_texts, target_lang)
            self._log(f"  - Translated {len(translations)} blocks")

            # Step 4: PDF 텍스트 교체
            self._log("[Step 4] Replacing texts in PDF...")
            debug_path = None
            if self.output_dir:
                debug_path = str(Path(self.output_dir) / "replace_debug.json")

            replace_result = replace_texts_in_pdf(
                pdf_path,
                translations,
                output_path,
                debug_path=debug_path,
            )

            result["translated_blocks"] = replace_result.get("replaced", 0)
            result["failed_blocks"] = replace_result.get("failed", 0)
            result["review_needed"] = replace_result.get("review_needed", 0)
            result["success"] = replace_result.get("success", False)

            self._log(f"  - Replaced: {replace_result.get('replaced', 0)}/{replace_result.get('total', 0)}")
            if replace_result.get("failed", 0) > 0:
                self._log(f"  - Failed: {replace_result.get('failed', 0)}")
            if replace_result.get("review_needed", 0) > 0:
                self._log(f"  - Review needed: {replace_result.get('review_needed', 0)}")

            # Step 5: 로그 저장
            if self.output_dir:
                self._save_log()
                self._save_translation_data(korean_texts, translations)

            self._log("=" * 60)
            self._log(f"Pipeline {'COMPLETED' if result['success'] else 'FAILED'}")
            self._log(f"Output: {output_path}")
            self._log("=" * 60)

        except Exception as e:
            self._log(f"[ERROR] Pipeline failed: {e}")
            result["error"] = str(e)
            logger.exception("Pipeline error")

        return result

    def _translate_texts(
        self,
        korean_texts: list[dict],
        target_lang: str = "en"
    ) -> list[dict]:
        """
        텍스트 블록들을 번역

        Args:
            korean_texts: 추출된 한글 텍스트 리스트
            target_lang: 목표 언어

        Returns:
            번역 데이터 리스트
        """
        if not self.llm_client:
            self._log("  [WARN] No LLM client. Using placeholder translations.")
            return self._placeholder_translations(korean_texts)

        translations = []

        # 배치 처리 (페이지별로 그룹화)
        page_groups = {}
        for item in korean_texts:
            page = item["page_num"]
            if page not in page_groups:
                page_groups[page] = []
            page_groups[page].append(item)

        for page_num, items in page_groups.items():
            self._log(f"    Page {page_num}: {len(items)} blocks")

            try:
                # 배치 번역
                batch_translations = self._translate_batch(items, target_lang)
                translations.extend(batch_translations)

            except Exception as e:
                self._log(f"    [ERROR] Page {page_num} translation failed: {e}")
                # 실패 시 placeholder 사용
                translations.extend(self._placeholder_translations(items))

        return translations

    def _translate_batch(
        self,
        items: list[dict],
        target_lang: str = "en"
    ) -> list[dict]:
        """배치 번역 (LLM 호출)"""
        # 프롬프트 생성
        prompt = self._build_translation_prompt(items, target_lang)

        # LLM 호출
        response = self.llm_client.complete(prompt)

        # 응답 파싱
        translations = self._parse_translation_response(response, items)

        return translations

    def _build_translation_prompt(
        self,
        items: list[dict],
        target_lang: str = "en"
    ) -> str:
        """번역 프롬프트 생성 (role 기반 차별화)"""
        prompt_parts = [
            f"Translate the following Korean texts to {target_lang.upper()}.",
            "",
            "Rules by text type:",
            "- TITLE: Keep concise and impactful (max 8 words)",
            "- HEADING: Clear section header (max 6 words)",
            "- BODY: Natural, flowing translation",
            "- BULLET: Keep concise (bullet symbols preserved separately)",
            "- CAPTION: Brief description (max 10 words)",
            "- FOOTER/SOURCE: Keep as brief as possible",
            "",
            "General rules:",
            "1. Translate naturally and fluently",
            "2. Keep proper nouns as-is if uncertain",
            "3. Keep numbers as digits, do NOT spell them out (10 → 10, not Ten)",
            "4. NEVER add ANY bullet symbols (-, *, •, ■, etc.) - they are preserved from original",
            "5. Do NOT add extra punctuation or quotes",
            "6. Output format: [BLOCK_ID]: translated text",
            "",
            "Texts to translate:",
        ]

        for item in items:
            block_id = item["block_id"]
            # prefix 제외한 텍스트로 번역 (원본 기호 보존)
            text = item.get("text_for_translation", item["text"]).strip()
            role = item.get("role", "body").upper()
            prompt_parts.append(f"[{block_id}] ({role}): {text}")

        prompt_parts.extend([
            "",
            "Translations:"
        ])

        return "\n".join(prompt_parts)

    def _parse_translation_response(
        self,
        response: str,
        items: list[dict]
    ) -> list[dict]:
        """LLM 응답 파싱"""
        translations = []

        # 블록 ID → 원본 데이터 매핑
        item_map = {item["block_id"]: item for item in items}

        # 응답 파싱 (패턴: [block_id]: translated text)
        import re
        pattern = r'\[([^\]]+)\]:\s*(.+?)(?=\[|$)'
        matches = re.findall(pattern, response, re.DOTALL)

        for block_id, translated in matches:
            block_id = block_id.strip()
            translated = translated.strip()

            # LLM이 추가한 bullet 기호 제거
            translated = re.sub(r'^[\-\*•■◆◇○●\s]+', '', translated).strip()

            if block_id in item_map:
                item = item_map[block_id]
                translations.append({
                    "page_num": item["page_num"],
                    "block_id": block_id,
                    "original": item["text"],
                    "translated": translated,
                    "bbox": item["bbox"],
                    "font": item["font"],
                    "size": item["size"],
                    "color": item.get("color", 0),
                    "role": item.get("role", "body"),
                    "prefix_width": item.get("prefix_width", 0.0),
                    "line_colors": item.get("line_colors", []),
                    "line_texts": item.get("line_texts", []),
                    "has_multi_color": item.get("has_multi_color", False),
                })

        # 매칭 안 된 항목은 원본 유지
        matched_ids = {m[0].strip() for m in matches}
        for item in items:
            if item["block_id"] not in matched_ids:
                translations.append({
                    "page_num": item["page_num"],
                    "block_id": item["block_id"],
                    "original": item["text"],
                    "translated": item["text"],  # 원본 유지
                    "bbox": item["bbox"],
                    "font": item["font"],
                    "size": item["size"],
                    "color": item.get("color", 0),
                    "role": item.get("role", "body"),
                    "prefix_width": item.get("prefix_width", 0.0),
                    "line_colors": item.get("line_colors", []),
                    "line_texts": item.get("line_texts", []),
                    "has_multi_color": item.get("has_multi_color", False),
                })

        return translations

    def _placeholder_translations(self, items: list[dict]) -> list[dict]:
        """Placeholder 번역 (테스트용)"""
        return [
            {
                "page_num": item["page_num"],
                "block_id": item["block_id"],
                "original": item["text"],
                "translated": f"[EN] {item['text'][:30]}...",
                "bbox": item["bbox"],
                "font": item["font"],
                "size": item["size"],
                "color": item.get("color", 0),
                "role": item.get("role", "body"),
                "prefix_width": item.get("prefix_width", 0.0),
            }
            for item in items
        ]

    def _save_log(self):
        """로그 파일 저장"""
        if not self.output_dir:
            return

        log_path = Path(self.output_dir) / "pdf_layer_pipeline.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.log_lines))

    def _save_translation_data(
        self,
        korean_texts: list[dict],
        translations: list[dict]
    ):
        """번역 데이터 저장"""
        if not self.output_dir:
            return

        # 원본 텍스트
        source_path = Path(self.output_dir) / "source_texts.json"
        with open(source_path, "w", encoding="utf-8") as f:
            json.dump(korean_texts, f, ensure_ascii=False, indent=2)

        # 번역 결과
        trans_path = Path(self.output_dir) / "translations.json"
        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)


def translate_pdf(
    pdf_path: str,
    output_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """
    PDF 번역 편의 함수

    Args:
        pdf_path: 원본 PDF 경로
        output_path: 출력 PDF 경로
        output_dir: 출력 디렉토리

    Returns:
        파이프라인 결과
    """
    pipeline = PDFLayerPipeline(output_dir=output_dir)
    return pipeline.run(pdf_path, output_path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        output_path = sys.argv[2] if len(sys.argv) > 2 else None

        result = translate_pdf(pdf_path, output_path)

        print("\n=== Result ===")
        print(f"Success: {result['success']}")
        print(f"Output: {result['output_path']}")
        print(f"Translated: {result['translated_blocks']}/{result['total_blocks']}")
    else:
        print("Usage: python pdf_layer_pipeline.py <input.pdf> [output.pdf]")
