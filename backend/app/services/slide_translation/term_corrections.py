"""
CSV 기반 용어 교정 로더

외부 CSV 파일에서 한국어-영어 용어 매핑을 로드하여
번역 프롬프트의 MANDATORY glossary로 사용.

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
from pathlib import Path
from typing import Optional

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
    """번역 프롬프트용 mandatory glossary 딕셔너리 반환.

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


def clear_cache():
    """캐시 초기화 (테스트용)."""
    global _TERM_CACHE, _TERM_FILE
    _TERM_CACHE = None
    _TERM_FILE = None
