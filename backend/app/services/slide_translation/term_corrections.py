"""
CSV 기반 용어 교정 로더

외부 CSV 파일에서 한국어-영어 용어 매핑을 로드하여
번역 프롬프트의 MANDATORY terminology로 사용.

CSV 형식:
    korean,english
    한계비용,Marginal cost
    기회비용,Opportunity cost

사용법:
    from .term_corrections import load_term_corrections, get_mandatory_terms

    terms = load_term_corrections()  # [(korean, english), ...]
    mandatory = get_mandatory_terms()  # {korean: english, ...}
"""

import csv
import os
import re
from pathlib import Path
from typing import Callable, Optional

try:
    from app.config import PROJECT_ROOT, USER_DATA_DIR
except ImportError:
    # 독립 실행 또는 테스트 환경
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
    USER_DATA_DIR = PROJECT_ROOT


# ── 캐시 ──────────────────────────────────────────────────────────────────────
_TERM_CACHE: Optional[dict] = None
_TERM_FILE: Optional[Path] = None


def _get_csv_path() -> Path:
    """용어집 CSV 파일 경로 반환.

    검색 순서:
    1. 환경변수 TERM_CORRECTIONS_FILE
    2. config/term_corrections.csv (프로젝트 루트)
    3. USER_DATA_DIR/config/term_corrections.csv
    """
    env_path = os.environ.get("TERM_CORRECTIONS_FILE")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    candidates = [
        PROJECT_ROOT / "config" / "term_corrections.csv",
        USER_DATA_DIR / "config" / "term_corrections.csv",
        Path(__file__).parent / "term_corrections.csv",
    ]

    for path in candidates:
        if path.exists():
            return path

    # 기본 경로 반환 (파일이 없어도)
    return PROJECT_ROOT / "config" / "term_corrections.csv"


def load_term_corrections(force_reload: bool = False) -> list[tuple[str, str]]:
    """CSV 파일에서 용어 매핑 로드.

    Args:
        force_reload: True면 캐시 무시하고 다시 로드

    Returns:
        [(korean, english), ...] - 긴 용어가 먼저 오도록 정렬됨
    """
    global _TERM_CACHE, _TERM_FILE

    file_path = _get_csv_path()

    # 캐시 확인
    if not force_reload and _TERM_CACHE is not None and _TERM_FILE == file_path:
        try:
            if file_path.exists() and file_path.stat().st_mtime == _TERM_CACHE.get("mtime"):
                return _TERM_CACHE.get("terms", [])
        except (OSError, PermissionError):
            pass

    terms = []

    if not file_path.exists():
        print(f"[TermCorrections] CSV 파일 없음: {file_path}")
        return terms

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                korean = (row.get("korean") or "").strip()
                english = (row.get("english") or "").strip()

                # 주석 라인 또는 빈 라인 무시
                if not korean or not english or korean.startswith("#"):
                    continue

                # 단일 글자 용어 제외 (다른 단어 오염 방지)
                if len(korean) < 2:
                    continue

                terms.append((korean, english))

        # 긴 용어가 먼저 매칭되도록 정렬
        terms.sort(key=lambda x: len(x[0]), reverse=True)

        _TERM_CACHE = {
            "terms": terms,
            "mtime": file_path.stat().st_mtime,
        }
        _TERM_FILE = file_path

        print(f"[TermCorrections] {len(terms)}개 용어 로드: {file_path}")

    except Exception as e:
        print(f"[TermCorrections] CSV 로드 실패: {e}")

    return terms


def get_mandatory_terms() -> dict[str, str]:
    """번역 프롬프트용 mandatory terminology 딕셔너리 반환.

    Returns:
        {korean: english, ...}
    """
    terms = load_term_corrections()
    return {korean: english for korean, english in terms}


def get_terms_in_text(text: str) -> dict[str, str]:
    """텍스트에 등장하는 용어만 추출.

    Args:
        text: 검색할 텍스트

    Returns:
        {korean: english, ...} - 텍스트에 등장한 용어만
    """
    if not text:
        return {}

    terms = load_term_corrections()
    found = {}

    for korean, english in terms:
        if korean in text:
            found[korean] = english

    return found


def build_term_replacer() -> Callable[[str], str]:
    """용어 치환 함수 생성.

    Generator 소비 문제, 빈 키, 대량 용어 등 edge case 방어.

    Returns:
        text를 받아 용어 치환된 text를 반환하는 함수
    """
    terms = load_term_corrections()  # 이미 list 반환, 긴 용어 먼저 정렬됨
    mapping = {korean: english for korean, english in terms}
    mapping.pop("", None)  # 빈 키 제거 (방어)

    if not mapping:
        return lambda text: text

    # 긴 용어가 먼저 매칭되도록 정렬 (load_term_corrections에서 이미 정렬됨)
    pattern = re.compile("|".join(re.escape(k) for k in mapping.keys()))

    def _replace(text: str) -> str:
        if not text:
            return text
        return pattern.sub(lambda m: mapping[m.group(0)], text)

    return _replace


def replace_terms_in_text(text: str) -> str:
    """텍스트 내 용어를 영어로 치환.

    Args:
        text: 원본 텍스트

    Returns:
        용어가 치환된 텍스트
    """
    replacer = build_term_replacer()
    return replacer(text)


def clear_cache():
    """캐시 초기화 (테스트용)."""
    global _TERM_CACHE, _TERM_FILE, _OCR_CORRECTIONS_CACHE
    _TERM_CACHE = None
    _TERM_FILE = None
    _OCR_CORRECTIONS_CACHE = None


# ── OCR 보정 ─────────────────────────────────────────────────────────────────
# OCR 오인식 보정: 잘못 인식된 한글 → 올바른 한글
# 용어집(한글→영어)과 별개로, 번역 전 OCR 텍스트 자체를 교정
#
# TODO: OCR 후처리 개선 (docs/slide/TODO_OCR_POSTPROCESS.md 참조)
#   - 현재: ocr_corrections.csv 수동 등록 방식만 지원
#   - 개선안 1: term_corrections.csv 기반 fuzzy matching (edit distance)
#   - 개선안 2: 한글 맞춤법 검사기 통합 (py-hanspell 등)
#   - 개선안 3: LLM 기반 OCR 후보정
# ─────────────────────────────────────────────────────────────────────────────

_OCR_CORRECTIONS_CACHE: Optional[dict] = None


def _get_ocr_corrections_path() -> Path:
    """OCR 보정 CSV 파일 경로 반환.

    검색 순서:
    1. 환경변수 OCR_CORRECTIONS_FILE
    2. config/ocr_corrections.csv (프로젝트 루트)
    """
    env_path = os.environ.get("OCR_CORRECTIONS_FILE")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    candidates = [
        PROJECT_ROOT / "config" / "ocr_corrections.csv",
        Path(__file__).parent / "ocr_corrections.csv",
    ]

    for path in candidates:
        if path.exists():
            return path

    return PROJECT_ROOT / "config" / "ocr_corrections.csv"


def load_ocr_corrections(force_reload: bool = False) -> dict[str, str]:
    """OCR 오인식 보정 매핑 로드.

    CSV 형식:
        typo,correct
        기게학습,기계학습
        컴뷰터,컴퓨터

    Args:
        force_reload: True면 캐시 무시하고 다시 로드

    Returns:
        {typo: correct, ...} - 긴 오타가 먼저 오도록 정렬됨
    """
    global _OCR_CORRECTIONS_CACHE

    if not force_reload and _OCR_CORRECTIONS_CACHE is not None:
        return _OCR_CORRECTIONS_CACHE

    corrections = {}
    file_path = _get_ocr_corrections_path()

    if not file_path.exists():
        # 파일이 없으면 빈 dict 반환 (정상 케이스)
        _OCR_CORRECTIONS_CACHE = corrections
        return corrections

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                typo = (row.get("typo") or "").strip()
                correct = (row.get("correct") or "").strip()

                if not typo or not correct or typo.startswith("#"):
                    continue

                if len(typo) < 2:
                    continue

                corrections[typo] = correct

        # 긴 오타가 먼저 매칭되도록 정렬된 dict로 변환
        corrections = dict(sorted(corrections.items(), key=lambda x: len(x[0]), reverse=True))
        _OCR_CORRECTIONS_CACHE = corrections

        print(f"[OCR Corrections] {len(corrections)}개 보정 규칙 로드: {file_path}")

    except Exception as e:
        print(f"[OCR Corrections] CSV 로드 실패: {e}")
        _OCR_CORRECTIONS_CACHE = {}

    return _OCR_CORRECTIONS_CACHE


def correct_ocr_text(text: str) -> str:
    """OCR 오인식 텍스트 보정.

    용어집(term_corrections.csv)의 한글 키를 기준으로
    비슷하지만 틀린 OCR 결과를 교정합니다.

    동작 방식:
    1. ocr_corrections.csv에서 명시적 오타→교정 매핑 적용
    2. term_corrections.csv의 한글 용어를 기준으로 유사도 기반 교정 (선택적)

    Args:
        text: OCR로 인식된 텍스트

    Returns:
        교정된 텍스트
    """
    if not text:
        return text

    # 1. 명시적 OCR 보정 매핑 적용
    corrections = load_ocr_corrections()
    if corrections:
        for typo, correct in corrections.items():
            if typo in text:
                text = text.replace(typo, correct)

    return text


def build_ocr_corrector() -> Callable[[str], str]:
    """OCR 보정 함수 생성 (성능 최적화).

    Returns:
        text를 받아 OCR 오타가 교정된 text를 반환하는 함수
    """
    corrections = load_ocr_corrections()

    if not corrections:
        return lambda text: text

    # 정규식 패턴 미리 컴파일
    pattern = re.compile("|".join(re.escape(k) for k in corrections.keys()))

    def _correct(text: str) -> str:
        if not text:
            return text
        return pattern.sub(lambda m: corrections[m.group(0)], text)

    return _correct
