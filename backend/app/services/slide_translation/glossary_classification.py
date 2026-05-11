"""
GPT-based Glossary Classification

추출된 후보를 GPT로 분류하여 glossary 생성

입력:
- document_candidates.json

출력:
- glossary.generated.json (자동 생성된 glossary)
- glossary.review.csv (검토 필요 항목)

역할:
- confidence 기반 policy 결정 (force/prefer/review)
- 후보 분류: person_name, organization, technical_term, common_word
"""
import json
from typing import Optional


def classify_candidates_with_gpt(
    candidates: list[dict],
    llm_client=None,
    batch_size: int = 20
) -> dict:
    """후보를 GPT로 분류

    Args:
        candidates: document_candidates.json의 후보 목록
        llm_client: LLM API 클라이언트 (None이면 mock 반환)
        batch_size: 한 번에 분류할 후보 수

    Returns:
        GPT 분류 결과 {"items": [...]}
    """
    if not candidates:
        return {"items": []}

    if llm_client is None:
        # mock 모드: 빈 결과 반환 (테스트용)
        return {"items": []}

    all_results = []

    print(f"[GlossaryClassification] 총 {len(candidates)}개 후보 분류 시작 (배치 크기: {batch_size})")

    # 배치 단위로 처리
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(candidates) + batch_size - 1) // batch_size
        print(f"[GlossaryClassification] 배치 {batch_num}/{total_batches} 처리 중 ({len(batch)}개 후보)...")

        prompt = _build_classification_prompt(batch)

        try:
            print(f"[GlossaryClassification] GPT API 호출 중...")
            response = llm_client.complete(prompt)
            print(f"[GlossaryClassification] GPT 응답 수신 완료 (길이: {len(response)})")
            batch_results = _parse_gpt_response(response)
            all_results.extend(batch_results)
            print(f"[GlossaryClassification] 배치 {batch_num} 완료: {len(batch_results)}개 결과")
        except Exception as e:
            print(f"[GlossaryClassification] GPT 호출 오류: {e}")
            import traceback
            traceback.print_exc()
            # 오류 시 uncertain으로 처리
            for c in batch:
                all_results.append({
                    "text": c["text"],
                    "category": "uncertain",
                    "english": "",
                    "confidence": 0.0,
                    "reason": f"GPT error: {e}"
                })

    return {"items": all_results}


def _build_classification_prompt(candidates: list[dict]) -> str:
    """GPT 분류 프롬프트 생성 (품질 최대화 버전)

    새 필드 활용:
    - suggested_translation: 괄호 병기에서 추출된 영어 번역
    - context_samples: 문맥 샘플 (분류 정확도 향상)
    - risk_flags: 품질 위험 플래그
    """
    candidate_texts = []
    for c in candidates:
        # 기본 정보
        text = c['text']
        kind_hint = c['kind_hint']
        count = c['count']
        pages = c.get('pages', [])

        # 추가 정보
        suggested = c.get('suggested_translation', '')
        contexts = c.get('context_samples', [])
        risks = c.get('risk_flags', [])

        # 후보 항목 구성
        parts = [f"- {text}"]
        parts.append(f"  hint: {kind_hint}, 출현: {count}회, 페이지: {pages}")

        # suggested_translation이 있으면 (고품질 힌트)
        if suggested:
            parts.append(f"  제안 번역: {suggested}")

        # risk_flags가 있으면
        if risks:
            parts.append(f"  주의: {', '.join(risks)}")

        # context_samples (최대 2개)
        if contexts:
            parts.append(f"  문맥 예시:")
            for ctx in contexts[:2]:
                # 너무 긴 문맥은 자르기
                ctx_short = ctx[:100] + "..." if len(ctx) > 100 else ctx
                parts.append(f"    \"{ctx_short}\"")

        candidate_texts.append("\n".join(parts))

    candidates_str = "\n\n".join(candidate_texts)

    prompt = f"""다음 한국어 단어/구문들을 분류해주세요.

각 항목에 대해 다음 정보를 JSON 형식으로 제공해주세요:
- text: 원본 텍스트
- category: person_name | organization | technical_term | common_word | uncertain
- english: 영어 번역 (제안 번역이 있으면 참고, 없으면 직접 판단)
- confidence: 0.0 ~ 1.0 (분류 확신도)
- reason: 분류 이유 (짧게)

분류 기준:
- person_name: 사람 이름 (교수명, 저자명 등)
- organization: 기관/대학/학과명
- technical_term: 전문 용어 (학술적/기술적 용어, 번역 시 일관성 필요)
- common_word: 일반 단어 (문맥에 따라 번역 달라짐, glossary 불필요)
- uncertain: 분류 불확실

힌트 해석:
- bilingual_term: 한영 병기 형태로 발견됨 (고품질, 제안 번역 신뢰도 높음)
- subterm_phrase: 문장 내 나열 구조에서 추출
- foreign_loanword: 외래어 패턴
- organization: 기관명 패턴
- title_phrase: 제목/소제목에서 추출
- short_korean: 2~4자 한글 (common_word일 가능성 있음)
- term_phrase_suffix: 접미사 패턴만으로 추출 (노이즈 가능성 있음)

주의 플래그:
- common_word_possible: 일반 단어일 가능성 높음
- suffix_based_only: 접미사만으로 판단, 재검토 필요

후보 목록:
{candidates_str}

JSON 형식으로만 응답해주세요:
{{"items": [...]}}"""

    return prompt


def _parse_gpt_response(response: str) -> list[dict]:
    """GPT 응답 파싱"""
    try:
        # JSON 부분만 추출
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response[start:end]
            data = json.loads(json_str)
            return data.get("items", [])
    except json.JSONDecodeError:
        pass
    return []


def policy_from_gpt_classification(item: dict) -> dict:
    """GPT 분류 결과에서 최종 policy 결정

    Policy 체계:
    - force: 반드시 고정 (사람 이름, 기관명, 약어, 제품명)
    - recommended: 권장 번역 (일반 전문용어, 긴 구문) - aliases 허용
    - suggest: 참고용 (일반 단어) - validation 없음

    Returns:
        {"policy": str, "protect": bool}
    """
    import re

    category = item.get("category", "uncertain")
    confidence = item.get("confidence", 0.0)
    text = item.get("text", "")
    english = item.get("english", "")

    # === force 대상 ===
    # 1. 사람 이름: 항상 force (높은 confidence)
    if category == "person_name":
        if confidence >= 0.85:
            return {"policy": "force", "protect": True}
        return {"policy": "recommended", "protect": False}

    # 2. 기관명: 항상 force (높은 confidence)
    if category == "organization":
        if confidence >= 0.80:
            return {"policy": "force", "protect": True}
        return {"policy": "recommended", "protect": False}

    # 3. 약어 감지: 영어가 대문자 2-6글자면 force
    # 예: NLP, AI, GPT, LSTM, CNN
    if english and re.match(r'^[A-Z]{2,6}$', english.strip()):
        return {"policy": "force", "protect": True}

    # === recommended 대상 ===
    # 4. technical_term: confidence와 길이에 따라 분류
    if category == "technical_term":
        # 짧은 용어 (5자 이하): force 가능
        if len(text) <= 5 and confidence >= 0.90:
            return {"policy": "force", "protect": True}
        # 긴 구문 (10자 초과): recommended
        if len(text) > 10:
            return {"policy": "recommended", "protect": False}
        # 중간 길이: confidence에 따라
        if confidence >= 0.85:
            return {"policy": "recommended", "protect": False}
        return {"policy": "suggest", "protect": False}

    # === suggest 대상 ===
    # 5. common_word: 항상 suggest
    if category == "common_word":
        return {"policy": "suggest", "protect": False}

    # uncertain / unknown: 길이에 따라
    if len(text) > 10:
        return {"policy": "suggest", "protect": False}
    return {"policy": "suggest", "protect": False}


def build_glossary_from_gpt_results(gpt_results: dict) -> dict:
    """GPT 분류 결과를 glossary 구조로 변환"""
    glossary = {
        "proper_nouns": {},
        "organizations": {},
        "terms": {},
        "common_words": {},
        "uncertain": {}
    }

    category_to_section = {
        "person_name": "proper_nouns",
        "organization": "organizations",
        "technical_term": "terms",
        "common_word": "common_words",
    }

    for item in gpt_results.get("items", []):
        text = item.get("text", "")
        if not text:
            continue

        category = item.get("category", "uncertain")
        policy_info = policy_from_gpt_classification(item)

        entry = {
            "en": item.get("english", ""),
            "policy": policy_info["policy"],
            "protect": policy_info["protect"],
            "type": category,
            "confidence": item.get("confidence", 0.0),
            "reason": item.get("reason", ""),
            "source_pages": item.get("evidence", {}).get("pages", []),
            "reviewed": False
        }

        # policy가 review면 uncertain으로
        if policy_info["policy"] == "review":
            glossary["uncertain"][text] = entry
        else:
            section = category_to_section.get(category, "uncertain")
            glossary[section][text] = entry

    return glossary


def merge_with_existing_glossary(
    generated: dict,
    existing: Optional[dict] = None
) -> dict:
    """기존 glossary와 병합 (기존 것 우선)"""
    if not existing:
        return generated

    merged = {
        "proper_nouns": {},
        "organizations": {},
        "terms": {},
        "common_words": {},
        "uncertain": {}
    }

    for section in merged.keys():
        # 기존 것 먼저
        merged[section].update(existing.get(section, {}))
        # 새 것 추가 (기존에 없는 것만)
        for key, value in generated.get(section, {}).items():
            if key not in merged[section]:
                merged[section][key] = value

    return merged


def extract_review_items(glossary: dict) -> list[dict]:
    """검토 필요 항목 추출 (CSV 출력용)"""
    review_items = []

    for section, items in glossary.items():
        for text, entry in items.items():
            if entry.get("policy") == "review" or not entry.get("reviewed", False):
                review_items.append({
                    "text": text,
                    "section": section,
                    "english": entry.get("en", ""),
                    "type": entry.get("type", ""),
                    "confidence": entry.get("confidence", 0.0),
                    "policy": entry.get("policy", ""),
                    "reason": entry.get("reason", ""),
                    "reviewed": entry.get("reviewed", False)
                })

    # confidence 오름차순 (낮은 것부터 검토)
    review_items.sort(key=lambda x: x["confidence"])
    return review_items


def save_glossary(glossary: dict, output_path: str):
    """glossary 저장"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)


def save_review_csv(review_items: list[dict], output_path: str):
    """검토 항목 CSV 저장"""
    import csv
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        if not review_items:
            f.write("text,section,english,type,confidence,policy,reason,reviewed\n")
            return

        writer = csv.DictWriter(f, fieldnames=review_items[0].keys())
        writer.writeheader()
        writer.writerows(review_items)


def load_glossary(input_path: str) -> dict:
    """glossary 로드"""
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)
