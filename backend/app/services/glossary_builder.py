"""
용어집 빌드 서비스 (GPT API 활용)

- 강의 슬라이드의 OCR 텍스트에서 전문용어 추출
- 한글 → 영어 번역 매핑 생성
- 캐시하여 동일 강의 재처리 시 API 재호출 방지

사용법:
    from backend.app.services.glossary_builder import GlossaryBuilder

    builder = GlossaryBuilder()
    glossary = builder.build_glossary(
        ocr_texts=["자료구조", "스택", "큐", ...],
        lecture_title="컴퓨터 구조 1장"
    )
    # glossary: {"자료구조": "Data Structure", "스택": "Stack", ...}
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# config.py가 dev/frozen 양쪽에서 .env를 적절한 위치에서 로드함 — 여기서 중복 로드 X
from app.config import USER_DATA_DIR, PROJECT_ROOT

# 용어집 캐시 위치:
#   - frozen: %LOCALAPPDATA%/Aunion AI/glossary/  (사용자별 영구 저장)
#   - dev: <root>/glossary/                       (저장소 표준 위치)
GLOSSARY_DIR = (USER_DATA_DIR / "glossary") if getattr(sys, 'frozen', False) else (PROJECT_ROOT / "glossary")
GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)


class GlossaryBuilder:
    """GPT API를 사용하여 용어집 빌드"""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
        self.model = model
        self._client = None

    @property
    def client(self):
        """OpenAI 클라이언트 지연 초기화"""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("openai 패키지가 필요합니다: pip install openai")
        return self._client

    def _get_cache_key(self, ocr_texts: list[str], lecture_title: str) -> str:
        """OCR 텍스트와 강의 제목으로 캐시 키 생성"""
        content = f"{lecture_title}::{','.join(sorted(ocr_texts))}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _get_cache_path(self, cache_key: str) -> Path:
        """캐시 파일 경로"""
        return GLOSSARY_DIR / f"glossary_{cache_key}.json"

    def _load_cache(self, cache_key: str) -> Optional[dict]:
        """캐시된 용어집 로드"""
        cache_path = self._get_cache_path(cache_key)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"[Glossary] 캐시 로드됨: {cache_path.name}")
                return data.get("terms", {})
            except Exception as e:
                print(f"[Glossary] 캐시 로드 실패: {e}")
        return None

    def _save_cache(self, cache_key: str, terms: dict, lecture_title: str):
        """용어집 캐시 저장"""
        cache_path = self._get_cache_path(cache_key)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "lecture_title": lecture_title,
                    "terms": terms,
                }, f, ensure_ascii=False, indent=2)
            print(f"[Glossary] 캐시 저장됨: {cache_path.name}")
        except Exception as e:
            print(f"[Glossary] 캐시 저장 실패: {e}")

    def _filter_korean_terms(self, texts: list[str]) -> list[str]:
        """한글 단어 추출 (긴 문장에서도 개별 단어 추출)"""
        # 한글 단어 패턴 (2~15자 연속 한글)
        korean_word_pattern = re.compile(r'[가-힣]{2,15}')
        extracted = set()

        for text in texts:
            text = text.strip()
            if not text:
                continue

            # 짧은 텍스트 (15자 이하): 전체가 용어 후보
            if len(text) <= 15:
                if korean_word_pattern.search(text):
                    extracted.add(text)
            else:
                # 긴 텍스트: 한글 단어만 개별 추출
                words = korean_word_pattern.findall(text)
                for word in words:
                    # 2~10자 단어만 (전문용어는 보통 이 범위)
                    if 2 <= len(word) <= 10:
                        extracted.add(word)

        print(f"[Glossary] 한글 단어 추출: {len(extracted)}개 (원본 {len(texts)}개 텍스트)")
        return list(extracted)

    def _extract_terms_via_gpt(self, korean_texts: list[str], lecture_title: str) -> dict:
        """GPT API로 전문용어 추출 및 번역 (25개씩 배치 호출)"""
        if not korean_texts:
            return {}

        # 25개씩 청크로 나눠서 여러 번 호출
        CHUNK_SIZE = 25
        all_terms = {}
        total_chunks = (len(korean_texts) + CHUNK_SIZE - 1) // CHUNK_SIZE

        for chunk_idx in range(0, len(korean_texts), CHUNK_SIZE):
            chunk = korean_texts[chunk_idx:chunk_idx + CHUNK_SIZE]
            chunk_num = chunk_idx // CHUNK_SIZE + 1
            print(f"[Glossary] GPT 호출 {chunk_num}/{total_chunks} ({len(chunk)}개 텍스트)")

            texts_str = "\n".join(f"- {t}" for t in chunk)

            prompt = f"""다음은 "{lecture_title}" 강의 슬라이드에서 추출한 한글 텍스트입니다.

{texts_str}

위 텍스트에서 **전문용어(학술용어, 기술용어)**만 추출하고, 영어 번역을 제공하세요.

규칙:
1. 일반적인 단어(예: "다음", "예시", "방법")는 제외
2. 전문용어만 추출 (예: "스택", "자료구조", "운영체제", "트랜잭션")
3. 영어 번역은 해당 분야의 표준 용어 사용

JSON 형식으로 응답하세요:
{{"자료구조": "Data Structure", "스택": "Stack", "운영체제": "Operating System"}}

전문용어가 없으면 빈 객체 {{}}를 반환하세요.
JSON만 반환하세요. 설명은 불필요합니다."""

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a technical translator specializing in academic terminology. Respond only with valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=2000,
                )

                content = response.choices[0].message.content.strip()

                # JSON 파싱 (```json ... ``` 블록 처리)
                if content.startswith("```"):
                    content = re.sub(r'^```(?:json)?\s*', '', content)
                    content = re.sub(r'\s*```$', '', content)

                chunk_terms = json.loads(content)
                all_terms.update(chunk_terms)
                print(f"  → {len(chunk_terms)}개 용어 추출")

            except json.JSONDecodeError as e:
                print(f"[Glossary] JSON 파싱 실패 (청크 {chunk_num}): {e}")
                print(f"  응답: {content[:200]}...")
            except Exception as e:
                print(f"[Glossary] GPT API 호출 실패 (청크 {chunk_num}): {e}")

        print(f"[Glossary] GPT 추출 완료: 총 {len(all_terms)}개 전문용어")
        return all_terms

    def build_glossary(
        self,
        ocr_texts: list[str],
        lecture_title: str = "Lecture",
        force_rebuild: bool = False,
    ) -> dict:
        """
        용어집 빌드 (캐시 우선)

        Args:
            ocr_texts: OCR로 추출한 텍스트 목록
            lecture_title: 강의 제목 (맥락 파악용)
            force_rebuild: True면 캐시 무시하고 재빌드

        Returns:
            dict: {한글: 영어} 용어 매핑
        """
        print(f"\n[Glossary] 용어집 빌드 시작: {lecture_title}")

        # 한글 전문용어 후보 필터링
        korean_texts = self._filter_korean_terms(ocr_texts)
        print(f"  - 한글 텍스트: {len(korean_texts)}개")

        if not korean_texts:
            print("  - 한글 텍스트 없음, 빈 용어집 반환")
            return {}

        # 캐시 확인
        cache_key = self._get_cache_key(korean_texts, lecture_title)

        if not force_rebuild:
            cached = self._load_cache(cache_key)
            if cached is not None:
                return cached

        # GPT로 전문용어 추출
        terms = self._extract_terms_via_gpt(korean_texts, lecture_title)

        # 캐시 저장
        if terms:
            self._save_cache(cache_key, terms, lecture_title)

        return terms

    def get_translation(self, korean_term: str, glossary: dict) -> Optional[str]:
        """
        용어집에서 번역 조회

        Args:
            korean_term: 한글 용어
            glossary: build_glossary()로 생성한 용어집

        Returns:
            영어 번역 또는 None
        """
        # 정확히 일치
        if korean_term in glossary:
            return glossary[korean_term]

        # 부분 일치 (용어가 텍스트에 포함된 경우)
        for ko, en in glossary.items():
            if ko in korean_term:
                return en

        return None
