"""
Image Text Translation (Phase 2)

이미지 내 텍스트 번역

입력:
- image_texts.deduplicated.json
- glossary.generated.json
- blocks.final.json (완료 후)

출력:
- image_texts.translated.json

역할:
- 이미지 내 라벨/텍스트를 glossary 기반으로 번역
- 일반 block과 동일한 glossary compliance 적용
"""
import re
from typing import Optional
from .config import cfg
from .token_protection import select_glossary_for_block


def translate_image_texts(
    image_texts: list[dict],
    glossary: dict,
    llm_client=None
) -> list[dict]:
    """이미지 내 텍스트 번역 (Phase 2)

    blocks.final.json 완료 후, 동일한 glossary로 번역.

    Args:
        image_texts: image_texts.deduplicated.json의 텍스트 리스트
        glossary: 문서 전체 glossary
        llm_client: LLM 클라이언트 (None이면 mock)

    Returns:
        번역된 텍스트 리스트
    """
    translated = []

    for item in image_texts:
        text = item.get("text", "").strip()
        if not text:
            item["english"] = ""
            item["translation_available"] = False
            translated.append(item)
            continue

        # glossary 매칭
        selected = select_glossary_for_text(text, glossary)

        # 짧은 텍스트는 간단한 prompt
        if len(text) <= 10:
            english = translate_short_label(text, selected, llm_client)
        else:
            english = translate_with_context(
                text, selected, item.get("type"), llm_client
            )

        item["english"] = english
        item["selected_glossary"] = selected
        item["translation_available"] = bool(english)
        translated.append(item)

    return translated


def select_glossary_for_text(text: str, glossary: dict) -> dict:
    """텍스트에 매칭되는 glossary 선택 (간소화 버전)"""
    return select_glossary_for_block(text, glossary)


def translate_short_label(
    text: str,
    glossary: dict,
    llm_client=None
) -> str:
    """짧은 라벨 번역 (1-10자)"""
    # glossary에 있으면 그대로 사용
    for section in ["proper_nouns", "organizations", "terms"]:
        if text in glossary.get(section, {}):
            return glossary[section][text].get("en", text)

    # 한글이 없으면 그대로 반환
    if not has_korean(text):
        return text

    # LLM으로 번역
    if llm_client is None:
        return text  # mock: 원문 반환

    prompt = f"""Translate this Korean label to English (1-5 words max):
Korean: {text}

Rules:
- Keep it short and concise
- Use title case for labels
- Return ONLY the English translation"""

    try:
        result = llm_client.complete(prompt)
        return result.strip()
    except Exception as e:
        print(f"[ImageTextTranslation] LLM 오류: {e}")
        return text


def translate_with_context(
    text: str,
    glossary: dict,
    text_type: Optional[str],
    llm_client=None
) -> str:
    """컨텍스트 기반 번역 (10자 초과)"""
    if not has_korean(text):
        return text

    if llm_client is None:
        return text  # mock: 원문 반환

    # glossary 힌트 생성
    glossary_hints = []
    for section in ["proper_nouns", "organizations", "terms"]:
        for ko, entry in glossary.get(section, {}).items():
            if ko in text:
                glossary_hints.append(f"  - {ko} → {entry.get('en', '')}")

    hints_str = "\n".join(glossary_hints) if glossary_hints else "  (none)"

    prompt = f"""Translate this Korean text from an image to English:

Korean: {text}
Image type: {text_type or 'label'}

Glossary (must use these translations):
{hints_str}

Rules:
- Use the glossary translations exactly as specified
- Keep formatting appropriate for {text_type or 'label'}
- Return ONLY the English translation"""

    try:
        result = llm_client.complete(prompt)
        return result.strip()
    except Exception as e:
        print(f"[ImageTextTranslation] LLM 오류: {e}")
        return text


def has_korean(text: str) -> bool:
    """한글 포함 여부"""
    return bool(re.search(r"[가-힣]", text))


def validate_image_text_translation(
    image_text: dict,
    glossary: dict
) -> list[dict]:
    """이미지 텍스트 번역 검증 (glossary compliance 포함)"""
    issues = []

    korean = image_text.get("text", "")
    english = image_text.get("english", "")
    selected = image_text.get("selected_glossary", {})

    # 1. 번역 누락
    if has_korean(korean) and not english:
        issues.append({
            "type": "image_text_missing_translation",
            "korean": korean
        })
        return issues

    # 2. glossary compliance (force만)
    for section in ["proper_nouns", "organizations", "terms"]:
        for ko, entry in selected.get(section, {}).items():
            if entry.get("policy") != "force":
                continue

            expected_en = entry.get("en", "")
            if not expected_en:
                continue

            if expected_en.lower() not in english.lower():
                issues.append({
                    "type": "image_text_glossary_violation",
                    "korean": ko,
                    "expected": expected_en,
                    "actual": english
                })

    # 3. 한글 잔존 체크
    if has_korean(english):
        # 허용되는 경우 체크
        remaining_korean = re.findall(r"[가-힣]+", english)
        for ko in remaining_korean:
            # uncertain에 있으면 허용
            if ko in glossary.get("uncertain", {}):
                continue
            # 짧은 고유명사 패턴이면 허용
            if 2 <= len(ko) <= 4 and looks_like_proper_noun(ko):
                continue

            issues.append({
                "type": "image_text_korean_remained",
                "korean": ko
            })

    return issues


def looks_like_proper_noun(korean: str) -> bool:
    """한글이 고유명사처럼 보이는지"""
    common_surnames = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
    if korean and korean[0] in common_surnames:
        return True
    return False


def save_translated_image_texts(texts: list[dict], output_path: str):
    """번역된 이미지 텍스트 저장"""
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "image_texts": texts,
            "count": len(texts),
            "translated_count": sum(1 for t in texts if t.get("translation_available"))
        }, f, ensure_ascii=False, indent=2)
