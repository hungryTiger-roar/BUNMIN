"""
Domain Glossary Pack System

구조:
- glossaries/ 폴더에 JSON 파일로 도메인별 용어집 저장
- 문서에서 키워드 추출 → 도메인 자동 감지
- common + top-k domains + document-generated glossary 병합

사용법:
1. detect_domains(document_text) → 상위 도메인 리스트
2. load_domain_glossaries(domains) → 병합된 glossary
3. merge_with_document_glossary(domain_glossary, generated_glossary)
"""

import json
import os
import re
from pathlib import Path
from typing import Optional


# Glossary pack 디렉토리
GLOSSARY_DIR = Path(__file__).parent / "glossaries"


def load_glossary_pack(pack_name: str) -> dict:
    """단일 glossary pack 로드"""
    pack_path = GLOSSARY_DIR / f"{pack_name}.json"
    if not pack_path.exists():
        return {"name": pack_name, "keywords": [], "terms": {}}

    try:
        with open(pack_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[DomainGlossary] Failed to load {pack_name}: {e}")
        return {"name": pack_name, "keywords": [], "terms": {}}


def list_available_packs() -> list[str]:
    """사용 가능한 glossary pack 목록"""
    if not GLOSSARY_DIR.exists():
        return []

    packs = []
    for f in GLOSSARY_DIR.glob("*.json"):
        packs.append(f.stem)
    return packs


def detect_domains(document_text: str, top_k: int = 2) -> list[str]:
    """문서에서 도메인 자동 감지

    Args:
        document_text: 전체 문서 텍스트 (OCR 결과 등)
        top_k: 상위 몇 개 도메인 선택

    Returns:
        감지된 도메인 이름 리스트 (점수 내림차순)
    """
    available_packs = list_available_packs()

    # common은 항상 포함, 점수 계산에서 제외
    domain_packs = [p for p in available_packs if p != "common"]

    if not domain_packs:
        return []

    # 각 도메인별 키워드 매칭 점수 계산
    scores = {}
    for pack_name in domain_packs:
        pack = load_glossary_pack(pack_name)
        keywords = pack.get("keywords", [])
        terms = pack.get("terms", {})

        score = 0
        # 키워드 매칭 (가중치 2)
        for keyword in keywords:
            if keyword in document_text:
                score += 2

        # 용어 매칭 (가중치 1)
        for term in terms.keys():
            if term in document_text:
                score += 1

        if score > 0:
            scores[pack_name] = score

    # 점수 내림차순 정렬
    sorted_domains = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    return sorted_domains[:top_k]


def load_domain_glossaries(domains: list[str], include_common: bool = True) -> dict:
    """도메인 glossary들을 병합하여 로드

    Args:
        domains: 도메인 이름 리스트
        include_common: common glossary 포함 여부

    Returns:
        병합된 glossary dict (표준 형식)
    """
    merged = {
        "proper_nouns": {},
        "organizations": {},
        "terms": {},
        "common_words": {},
        "uncertain": {}
    }

    # 로드할 pack 목록 (common 먼저, 그 다음 도메인들)
    packs_to_load = []
    if include_common:
        packs_to_load.append("common")
    packs_to_load.extend(domains)

    for pack_name in packs_to_load:
        pack = load_glossary_pack(pack_name)
        pack_terms = pack.get("terms", {})

        for ko_term, entry in pack_terms.items():
            # 표준 glossary 형식으로 변환
            merged["terms"][ko_term] = {
                "en": entry.get("en", ""),
                "policy": entry.get("policy", "recommended"),
                "protect": entry.get("policy") == "force",
                "type": "domain_term",
                "confidence": 1.0,
                "source": f"glossary_pack:{pack_name}",
                "critical": entry.get("policy") == "force"  # force policy면 critical
            }

    return merged


def merge_with_document_glossary(
    domain_glossary: dict,
    generated_glossary: dict
) -> dict:
    """도메인 glossary와 문서 생성 glossary 병합

    도메인 glossary가 우선 (force 정책이므로)

    Args:
        domain_glossary: 도메인 glossary (force 용어들)
        generated_glossary: GPT가 생성한 문서별 glossary

    Returns:
        병합된 glossary
    """
    merged = {
        "proper_nouns": {},
        "organizations": {},
        "terms": {},
        "common_words": {},
        "uncertain": {}
    }

    # 1. 생성된 glossary 먼저 (나중에 도메인으로 덮어씀)
    for section in merged.keys():
        merged[section].update(generated_glossary.get(section, {}))

    # 2. 도메인 glossary로 덮어쓰기 (force)
    for section in merged.keys():
        merged[section].update(domain_glossary.get(section, {}))

    return merged


def get_critical_terms_from_glossary(glossary: dict, document_text: str) -> set:
    """glossary에서 critical term 추출 (문서에 등장한 것만)

    policy=force인 용어 중 실제 문서에 등장한 것만 critical로 사용

    Args:
        glossary: 전체 glossary
        document_text: 문서 전체 텍스트

    Returns:
        critical term set
    """
    critical_terms = set()

    for section in ["terms", "proper_nouns", "organizations"]:
        for ko_term, entry in glossary.get(section, {}).items():
            # policy=force 또는 critical=true인 경우만
            is_critical = (
                entry.get("policy") == "force" or
                entry.get("critical") is True
            )

            if not is_critical:
                continue

            # 4글자 이상 전문용어만 부분 매칭 허용
            # 3글자 이하는 정확히 일치해야 함
            if len(ko_term) >= 4:
                if ko_term in document_text:
                    critical_terms.add(ko_term)
            else:
                # 짧은 용어는 단어 경계에서만 매칭
                # (다른 단어의 일부가 아닐 때만)
                pattern = rf"(?<![가-힣]){re.escape(ko_term)}(?![가-힣])"
                if re.search(pattern, document_text):
                    critical_terms.add(ko_term)

    return critical_terms


def auto_detect_and_load_glossary(
    document_text: str,
    generated_glossary: Optional[dict] = None,
    top_k: int = 2
) -> tuple[dict, list[str]]:
    """문서 기반 자동 도메인 감지 및 glossary 로드

    Args:
        document_text: 문서 전체 텍스트
        generated_glossary: GPT 생성 glossary (optional)
        top_k: 상위 몇 개 도메인 선택

    Returns:
        (merged_glossary, detected_domains)
    """
    # 1. 도메인 자동 감지
    detected_domains = detect_domains(document_text, top_k=top_k)

    # 2. 도메인 glossary 로드 (common 포함)
    domain_glossary = load_domain_glossaries(detected_domains, include_common=True)

    # 3. 문서 생성 glossary와 병합
    if generated_glossary:
        final_glossary = merge_with_document_glossary(domain_glossary, generated_glossary)
    else:
        final_glossary = domain_glossary

    return final_glossary, detected_domains
