"""
PDF 텍스트 레이어 기반 번역 파이프라인

[역할]
- 전체 번역 파이프라인 조율
- PDF 텍스트 레이어 직접 수정 (한글 → 영어)
- 이미지 기반 방식보다 품질이 높고 벡터 텍스트 유지

[호출 경로]
slides.py (router) → pdf_pipeline.py (이 파일)
  ├── pdf_text_extractor.py (텍스트 추출)
  ├── pdf_text_replacer.py (텍스트 교체)
  ├── llm_client.py (LLM 호출)
  └── bbox_analyzer.py (VLM 레이아웃 분석)

[주요 메서드]
- run(): 전체 파이프라인 실행
- _translate_batch(): LLM 배치 번역
- _build_translation_prompt(): 번역 프롬프트 생성
- _parse_translation_response(): LLM 응답 파싱

[주의]
- multi-color 렌더링은 pdf_text_replacer.py에서 처리
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
from .bbox_analyzer import analyze_page_layout

logger = logging.getLogger(__name__)


def _is_invalid_translation(text: str) -> bool:
    """무효한 번역인지 확인 (재시도 필요)

    무효 케이스:
    - "???" 또는 "??" 등 물음표만 있는 경우
    - "..." 또는 ".." 등 마침표만 있는 경우
    - "[untranslatable]", "[unknown]" 등 메타 텍스트
    - 빈 문자열 또는 공백만
    - 영문자/숫자가 전혀 없는 경우 (기호만)
    """
    import re

    if not text or not text.strip():
        return True

    text = text.strip()

    # 물음표/마침표만 있는 경우
    if re.match(r'^[\?\.\!\s]+$', text):
        return True

    # 메타 텍스트 패턴
    invalid_patterns = [
        r'^\[.*\]$',  # [anything]
        r'^untranslat',  # untranslatable, untranslated
        r'^unknown$',
        r'^n/?a$',
        r'^\?+$',
        r'^\.+$',
    ]
    for pattern in invalid_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True

    # 영문자나 숫자가 전혀 없으면 무효 (기호/구두점만)
    if not re.search(r'[A-Za-z0-9가-힣]', text):
        return True

    return False


class PDFLayerPipeline:
    """PDF 레이어 기반 번역 파이프라인"""

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        output_dir: Optional[str] = None,
        on_page_complete: Optional[callable] = None,
        glossary: Optional[dict] = None,
    ):
        self.llm_client = llm_client or get_default_llm_client()
        self.output_dir = output_dir
        self.on_page_complete = on_page_complete  # 페이지 완료 시 콜백 (page_num: int)
        self.glossary = glossary or {}  # {한글: 영어} 용어집
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

            # Step 2.5: VLM 레이아웃 분석 (선택적)
            layout_analysis = None
            try:
                self._log("[Step 2.5] Analyzing page layout with VLM...")
                layout_analysis = self._analyze_layout_with_vlm(pdf_path, korean_texts)
                if layout_analysis:
                    on_image_count = sum(1 for b in layout_analysis.get("blocks", []) if b.get("on_image_background"))
                    self._log(f"  - Analyzed {len(layout_analysis.get('blocks', []))} blocks")
                    self._log(f"  - On image background: {on_image_count}")
                else:
                    self._log("  - VLM not available, using heuristics")
            except Exception as e:
                self._log(f"  - VLM analysis skipped: {e}")

            # Step 3: 번역
            self._log("[Step 3] Translating texts...")
            translations = self._translate_texts(korean_texts, target_lang)
            self._log(f"  - Translated {len(translations)} blocks")

            # 레이아웃 분석 결과를 translations에 반영
            if layout_analysis:
                translations = self._apply_layout_analysis(translations, layout_analysis)

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

        processed_pages = 0
        total_page_count = len(page_groups)

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

            # 페이지 완료 콜백 호출
            processed_pages += 1
            if self.on_page_complete:
                try:
                    self.on_page_complete(processed_pages)
                except Exception as cb_err:
                    self._log(f"    [WARN] Page complete callback error: {cb_err}")

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

        # 디버그: LLM 응답 로깅 (첫 500자)
        logger.debug(f"LLM response (first 500 chars): {response[:500] if response else 'EMPTY'}")

        # 응답 파싱
        translations = self._parse_translation_response(response, items)

        # 파싱 결과 검증
        parsed_count = len([t for t in translations if t.get("translated") != t.get("original")])
        if parsed_count < len(items):
            logger.warning(f"Only {parsed_count}/{len(items)} blocks were translated. Check LLM response format.")

        return translations

    def _build_translation_prompt(
        self,
        items: list[dict],
        target_lang: str = "en"
    ) -> str:
        """번역 프롬프트 생성 (role 기반 차별화)"""
        prompt_parts = [
            f"Translate the following Korean texts to {target_lang.upper()}.",
        ]

        # Glossary 먼저 (가장 중요)
        if self.glossary:
            prompt_parts.append("")
            prompt_parts.append("=== MANDATORY TERMINOLOGY (YOU MUST USE THESE EXACT WORDS) ===")
            for ko, en in self.glossary.items():
                prompt_parts.append(f"  {ko} = {en}")
            prompt_parts.append("=== END TERMINOLOGY ===")

        # 현재 배치에서 반복되는 한국어 단어 감지
        from collections import Counter
        all_text = " ".join(item.get("text_for_translation", item["text"]) for item in items)
        # 2글자 이상 한글 단어 추출
        import re
        korean_words = re.findall(r'[가-힣]{2,}', all_text)
        word_counts = Counter(korean_words)
        repeated_words = [word for word, count in word_counts.items() if count >= 2]

        if repeated_words:
            prompt_parts.append("")
            prompt_parts.append(f"WARNING: These Korean words appear multiple times. Use the SAME English word for each:")
            prompt_parts.append(f"  {', '.join(repeated_words)}")

        prompt_parts.extend([
            "",
            "Rules by text type:",
            "- TITLE: Keep concise and impactful (max 8 words)",
            "- HEADING: Clear section header (max 6 words)",
            "- BODY: Natural, flowing translation",
            "- BULLET: Sentence case (capitalize first word only), keep concise (bullet symbols preserved separately)",
            "- CAPTION: Brief description (max 10 words)",
            "- FOOTER/SOURCE: Keep as brief as possible",
            "",
            "General rules:",
            "1. Translate to fit the overall context and flow of the document",
            "2. Keep proper nouns as-is if uncertain",
            "3. Keep numbers as digits (10 → 10, not Ten)",
            "4. NEVER add bullet symbols (-, *, •, ■) - preserved from original",
            "5. Do NOT add extra punctuation or quotes",
            "6. Keep symbols (⇒, →, ·) exactly in place",
            "7. ALWAYS translate parentheses and their contents",
            "8. If Korean has English in parentheses, keep ONLY the English",
            "9. Output format: [BLOCK_ID]: translated text",
        ])

        prompt_parts.append("")
        prompt_parts.append("Texts to translate:")

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

        # 1차 시도: 정규식 파싱
        pattern = r'\[([^\]]+)\]:\s*(.+?)(?=\n\[|\Z)'
        matches = re.findall(pattern, response, re.DOTALL)

        # 2차 시도: 라인별 파싱 (1차 실패 시)
        if not matches:
            for line in response.strip().split('\n'):
                line = line.strip()
                if line.startswith('[') and ']:' in line:
                    bracket_end = line.index(']:')
                    block_id = line[1:bracket_end]
                    translated = line[bracket_end + 2:].strip()
                    if block_id and translated:
                        matches.append((block_id, translated))

        invalid_ids = []
        for block_id, translated in matches:
            block_id = block_id.strip()
            translated = translated.strip()

            # LLM이 추가한 bullet 기호 제거
            translated = re.sub(r'^[\-\*•■◆◇○●\s]+', '', translated).strip()

            # 무효 번역 체크 (???, ... 등)
            if _is_invalid_translation(translated):
                invalid_ids.append(block_id)
                logger.warning(f"Invalid translation for {block_id}: '{translated[:30]}' → will retry")
                continue  # 무효 번역은 건너뛰기 (매칭 안 된 것으로 처리됨)

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

        if invalid_ids:
            self._log(f"    [WARN] Invalid translations filtered: {len(invalid_ids)} blocks")

        # 매칭 안 된 항목 또는 무효 번역은 원본 유지
        matched_ids = {m[0].strip() for m in matches} - set(invalid_ids)
        for item in items:
            if item["block_id"] not in matched_ids:
                # 파싱 실패 로깅
                logger.warning(f"Translation parsing failed for {item['block_id']}: '{item['text'][:50]}...'")
                logger.debug(f"LLM response was: {response[:500]}...")
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

    def _analyze_layout_with_vlm(
        self,
        pdf_path: str,
        korean_texts: list[dict]
    ) -> Optional[dict]:
        """
        VLM으로 페이지 레이아웃 분석

        Args:
            pdf_path: PDF 파일 경로
            korean_texts: 추출된 한글 텍스트 블록들

        Returns:
            레이아웃 분석 결과 또는 None
        """
        import fitz
        from PIL import Image
        import io

        try:
            doc = fitz.open(pdf_path)
            all_blocks = []

            # 페이지별로 그룹화
            page_groups = {}
            for item in korean_texts:
                page_num = item["page_num"]
                if page_num not in page_groups:
                    page_groups[page_num] = []
                page_groups[page_num].append(item)

            # 각 페이지 분석
            for page_num, blocks in page_groups.items():
                if page_num < 1 or page_num > len(doc):
                    continue

                page = doc[page_num - 1]

                # 페이지를 이미지로 렌더링
                mat = fitz.Matrix(2.0, 2.0)  # 2x 해상도
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                page_image = Image.open(io.BytesIO(img_data))

                # bbox 좌표를 이미지 해상도에 맞게 조정
                scaled_blocks = []
                for block in blocks:
                    scaled_block = block.copy()
                    bbox = block.get("bbox", [0, 0, 0, 0])
                    # 2x 스케일
                    scaled_block["bbox"] = [v * 2 for v in bbox]
                    scaled_blocks.append(scaled_block)

                # VLM 분석
                analysis = analyze_page_layout(page_image, scaled_blocks, use_vlm=True)

                # bbox를 원래 좌표로 복원하고 결과 저장
                for block_result in analysis.get("blocks", []):
                    all_blocks.append(block_result)

            doc.close()

            return {
                "blocks": all_blocks,
                "merge_groups": []  # TODO: 페이지 간 병합 그룹
            }

        except Exception as e:
            self._log(f"  - Layout analysis error: {e}")
            return None

    def _apply_layout_analysis(
        self,
        translations: list[dict],
        layout_analysis: dict
    ) -> list[dict]:
        """
        레이아웃 분석 결과를 번역 데이터에 적용

        Args:
            translations: 번역된 텍스트 리스트
            layout_analysis: VLM 분석 결과

        Returns:
            분석 결과가 반영된 번역 리스트
        """
        # block_id → 분석 결과 매핑
        analysis_map = {}
        for block in layout_analysis.get("blocks", []):
            block_id = block.get("block_id", "")
            analysis_map[block_id] = block

        # 각 번역에 분석 결과 추가
        for trans in translations:
            block_id = trans.get("block_id", "")
            has_prefix = bool(trans.get("prefix", ""))

            if block_id in analysis_map:
                analysis = analysis_map[block_id]
                trans["on_image_background"] = analysis.get("on_image_background", False)
                trans["expand_allowed"] = analysis.get("expand_allowed", True)
                # VLM 결과가 있어도 prefix가 있으면 기본적으로 유지 (VLM이 명시적으로 False 반환 시만 제거)
                vlm_keep_prefix = analysis.get("keep_prefix")
                if vlm_keep_prefix is None:
                    trans["keep_prefix"] = has_prefix  # VLM 결과 없으면 prefix 존재 여부로 판단
                else:
                    trans["keep_prefix"] = vlm_keep_prefix or has_prefix  # prefix 있으면 우선 유지
            else:
                # 기본값
                trans["on_image_background"] = False
                trans["expand_allowed"] = True
                trans["keep_prefix"] = has_prefix

        return translations


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
