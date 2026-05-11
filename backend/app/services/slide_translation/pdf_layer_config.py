"""
PDF Layer Pipeline Configuration

[역할]
- Role 분류 정책 (레이아웃/스타일 기반, 문자열 패턴 최소화)
- Merge 정책 (structural role 병합 금지)
- Fragment detection 정책 (severity levels)
- Prompt 생성용 role metadata

[원칙]
- 특정 PDF나 도메인에 종속되지 않는 일반화된 규칙
- 문자열 패턴보다 레이아웃/스타일 feature 우선
- 확장 가능한 구조

[사용처]
- pdf_text_extractor.py: role 분류
- pdf_pipeline.py: prompt 생성, fragment detection
- pdf_text_replacer.py: role별 렌더링 정책
"""
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# Role Classification Config (레이아웃/스타일 기반)
# =============================================================================

@dataclass
class RoleScoreWeights:
    """
    Role 분류에 사용되는 feature별 가중치

    원칙: 문자열 패턴보다 레이아웃 feature에 높은 가중치
    """
    # 레이아웃 features (높은 가중치)
    position: float = 0.25         # bbox 위치 (상단/중단/하단)
    font_size: float = 0.30        # 폰트 크기 (상대적) - 증가
    text_length: float = 0.15      # 텍스트 길이

    # 스타일 features (중간 가중치)
    color_diff: float = 0.15       # 인접 라인과 색상 차이
    has_bullet: float = 0.10       # bullet/prefix 여부

    # 구조 패턴 (증가 - 명확한 신호)
    structure_pattern: float = 0.20  # 콜론, 물음표 등 구조적 패턴
    question_mark: float = 0.40      # 물음표로 끝나는 문장 (강한 신호)
    colon_structure: float = 0.35    # Term: Definition 구조 (강한 신호)


@dataclass
class RoleThresholds:
    """
    Role 확정을 위한 최소 score threshold

    높은 threshold = 더 확실해야 확정
    """
    title: float = 0.5
    heading: float = 0.45
    section_header: float = 0.55   # 레이아웃 + 구조 패턴 필요
    principle_title: float = 0.55  # 레이아웃 + 구조 패턴 필요
    option: float = 0.6            # prefix 패턴 필수
    question: float = 0.5          # 물음표 또는 구조
    term_definition: float = 0.5   # 콜론 + 색상 차이
    example: float = 0.5           # 예시 패턴 (예), Example: 등)
    bullet: float = 0.5
    caption: float = 0.4
    footer: float = 0.5
    default: float = 0.3           # body 기본값


@dataclass
class LayoutConfig:
    """
    레이아웃 기반 role 감지 설정

    문자열 패턴이 아닌 위치/크기/스타일로 판단
    """
    # === 위치 기준 (페이지 비율) ===
    title_y_max: float = 0.15      # 상단 15% 이내 = title 후보
    footer_y_min: float = 0.85     # 하단 15% = footer 후보
    center_x_tolerance: float = 0.15  # 중앙 정렬 허용 오차

    # === 폰트 크기 기준 (pt) ===
    large_font_min: float = 20.0   # 큰 폰트 (title)
    medium_font_min: float = 14.0  # 중간 폰트 (heading)
    small_font_max: float = 10.0   # 작은 폰트 (caption/footer)

    # === 텍스트 길이 기준 (문자 수) ===
    short_text_max: int = 50       # 짧은 텍스트 (title/heading 후보)
    very_short_max: int = 30       # 매우 짧은 텍스트 (label)
    option_text_max: int = 100     # 선택지 최대 길이

    # === Term:Definition 기준 ===
    term_max_words: int = 5        # Term 부분 최대 단어 수
    definition_min_chars: int = 10  # Definition 부분 최소 문자 수


@dataclass
class StructurePatterns:
    """
    구조적 패턴 (일반화된 형태만)

    주의: 특정 도메인 단어(Principle, 원리 등)는 포함하지 않음
    """
    # === 선택지 prefix 패턴 ===
    # a), b), 1), (가), ① 등 - 보편적인 선택지 형태
    option_prefix: str = r'^(?:[a-zA-Z]\s*[\)\.]|[①②③④⑤⑥⑦⑧⑨⑩]|\([가-힣a-zA-Z0-9]\)|\d\s*[\)\.])(?:\s|$)'

    # === 콜론 구조 패턴 ===
    # "짧은텍스트: 긴텍스트" 형태 (Term: Definition)
    colon_structure: str = r'^([^:]+)[:]\s*(.+)$'

    # === 콜론 제외 패턴 (이것들은 term_definition이 아님) ===
    colon_exclude: list = field(default_factory=lambda: [
        r'^\d{1,2}:\d{2}',    # 시간 (10:30)
        r'^https?://',        # URL
        r'^\d+:$',            # 숫자만: (1:)
    ])

    # === 물음표 패턴 ===
    question_ending: str = r'\?\s*$'

    # === Bullet 패턴 ===
    bullet_prefix: str = r'^[\-\•\·\◦\▪\▸]\s'


# =============================================================================
# Merge Policy Config
# =============================================================================

@dataclass
class MergePolicy:
    """
    Role별 병합 정책

    structural role은 독립 유지, body role은 자유 병합
    """
    # 절대 병합하면 안 되는 structural roles
    never_merge_roles: list = field(default_factory=lambda: [
        "section_header",
        "principle_title",
        "option",
        "question",
        "term_definition",
        "example",  # 예시 라인은 항상 독립
    ])

    # 같은 role끼리만 병합 가능한 roles
    same_role_only: list = field(default_factory=lambda: [
        "title",
        "heading",
    ])

    # 자유롭게 병합 가능한 body roles
    body_roles: list = field(default_factory=lambda: [
        "body",
        "bullet",
        "caption",
    ])


# =============================================================================
# Fragment Detection Config
# =============================================================================

@dataclass
class FragmentSignal:
    """Fragment 신호 정의"""
    pattern: str
    severity: str  # "strong", "weak"
    description: str


@dataclass
class FragmentDetectionConfig:
    """
    Broken fragment detection 설정

    Strong signal: 거의 확실히 broken
    Weak signal: 문맥에 따라 정상일 수 있음
    """
    # Strong signals (높은 확률로 broken)
    strong_signals: list = field(default_factory=lambda: [
        FragmentSignal(r"'$", "strong", "ends_with_apostrophe"),
        FragmentSignal(r"-$", "strong", "ends_with_hyphen"),
        FragmentSignal(r"\([^)]*$", "strong", "unclosed_parenthesis"),
        FragmentSignal(r"\[[^\]]*$", "strong", "unclosed_bracket"),
        # 제어문자 포함 (U+0000-U+001F, U+007F-U+009F, U+FFBE 등)
        FragmentSignal(r"[\x00-\x1f\x7f-\x9f\uffbe\ufffe\uffff]", "strong", "contains_control_char"),
        # 영어 단어가 hyphen으로 끝남 (real- 같은 패턴)
        FragmentSignal(r"[a-zA-Z]-\s*$", "strong", "english_word_hyphenated"),
    ])

    # Weak signals (문맥에 따라 정상일 수 있음)
    weak_signals: list = field(default_factory=lambda: [
        FragmentSignal(r",$", "weak", "ends_with_comma"),
        FragmentSignal(r"\s(and|or|but)$", "weak", "ends_with_conjunction"),
        FragmentSignal(r"\s(the|a|an|to|in|of|for|with|by|from)$", "weak", "ends_with_preposition"),
    ])

    # Strong signal 1개 이상이면 broken
    strong_threshold: int = 1

    # Weak signal만 있을 때 retry 후보로 표시할 최소 개수
    weak_retry_threshold: int = 2

    # 최소 텍스트 길이 (이보다 짧으면 체크 안 함)
    min_text_length: int = 5


# =============================================================================
# Prompt Generation Config
# =============================================================================

@dataclass
class RolePromptMetadata:
    """Role별 prompt 생성 메타데이터"""
    mode: str                    # "title", "body", "short", "preserve_format"
    max_words: Optional[int]     # 최대 단어 수 (None = 제한 없음)
    constraints: list            # 적용할 제약 조건들


# Role별 기본 prompt 메타데이터
ROLE_PROMPT_METADATA = {
    "title": RolePromptMetadata(
        mode="title",
        max_words=8,
        constraints=["concise", "impactful", "title_case"]
    ),
    "section_header": RolePromptMetadata(
        mode="preserve_format",
        max_words=10,
        constraints=["preserve_number", "preserve_structure"]
    ),
    "principle_title": RolePromptMetadata(
        mode="preserve_format",
        max_words=None,
        constraints=["preserve_number", "preserve_colon"]
    ),
    "heading": RolePromptMetadata(
        mode="title",
        max_words=6,
        constraints=["concise"]
    ),
    "term_definition": RolePromptMetadata(
        mode="preserve_format",
        max_words=None,
        constraints=["preserve_colon", "definition_capitalized"]
    ),
    "question": RolePromptMetadata(
        mode="body",
        max_words=None,
        constraints=["sentence_case", "natural_question", "preserve_question_mark"]
    ),
    "option": RolePromptMetadata(
        mode="short",
        max_words=15,
        constraints=["preserve_prefix", "capitalize_first"]
    ),
    "body": RolePromptMetadata(
        mode="body",
        max_words=None,
        constraints=["natural", "flowing", "capitalize_first"]
    ),
    "bullet": RolePromptMetadata(
        mode="body",
        max_words=None,
        constraints=["capitalize_first", "concise"]
    ),
    "caption": RolePromptMetadata(
        mode="short",
        max_words=10,
        constraints=["brief", "capitalize_first"]
    ),
    "footer": RolePromptMetadata(
        mode="short",
        max_words=5,
        constraints=["minimal"]
    ),
    "source": RolePromptMetadata(
        mode="short",
        max_words=5,
        constraints=["minimal"]
    ),
    "example": RolePromptMetadata(
        mode="body",
        max_words=None,
        constraints=["preserve_prefix", "natural", "capitalize_first"]  # "예)" 등 prefix 보존
    ),
}


# =============================================================================
# Font Size Policy
# =============================================================================

@dataclass
class FontSizePolicy:
    """Role별 최소 폰트 크기 정책"""
    title: float = 14.0
    section_header: float = 12.0
    principle_title: float = 12.0
    heading: float = 12.0
    term_definition: float = 10.0
    question: float = 10.0
    option: float = 10.0
    example: float = 10.0
    body: float = 10.0
    bullet: float = 10.0
    caption: float = 6.0
    footer: float = 6.0
    source: float = 6.0
    default: float = 8.0


# =============================================================================
# Global Config Instance
# =============================================================================

@dataclass
class PDFLayerConfig:
    """PDF Layer Pipeline 전체 설정"""
    role_weights: RoleScoreWeights = field(default_factory=RoleScoreWeights)
    role_thresholds: RoleThresholds = field(default_factory=RoleThresholds)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    patterns: StructurePatterns = field(default_factory=StructurePatterns)
    merge_policy: MergePolicy = field(default_factory=MergePolicy)
    fragment_detection: FragmentDetectionConfig = field(default_factory=FragmentDetectionConfig)
    font_size_policy: FontSizePolicy = field(default_factory=FontSizePolicy)


# 싱글톤 인스턴스
_config: Optional[PDFLayerConfig] = None


def get_config() -> PDFLayerConfig:
    """설정 인스턴스 반환 (싱글톤)"""
    global _config
    if _config is None:
        _config = PDFLayerConfig()
    return _config


def reset_config():
    """설정 초기화 (테스트용)"""
    global _config
    _config = None
