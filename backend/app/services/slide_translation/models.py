"""
슬라이드 번역 파이프라인 데이터 모델

[역할]
- PDF Layer / OCR 공통 데이터 구조 정의
- extract() → translate() → apply() 간 계약

[주요 타입]
- FontInfo: PDF Layer 폰트 메타데이터
- TextBlock: 추출된 텍스트 블록 (PDF Layer / OCR 공통)
"""
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class FontInfo:
    """PDF Layer 폰트 메타데이터

    PDF Layer에서는 필수, OCR에서는 None
    """
    name: str           # 폰트 이름 (예: "HYkanB", "맑은고딕")
    size: float         # 폰트 크기 (pt)
    color: int          # RGB as integer (예: 12582912)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FontInfo":
        return cls(
            name=d.get("name", ""),
            size=d.get("size", 12.0),
            color=d.get("color", 0),
        )


@dataclass
class TextBlock:
    """추출된 텍스트 블록 (PDF Layer / OCR 공통)

    Attributes:
        block_id: 안정적 ID (pdf_p{page}_b{block} / ocr_p{page}_r{region})
        source: "pdf" 또는 "ocr"
        page: 페이지 번호 (0-indexed)
        text: 원문 텍스트 (apply까지 유지)
        bbox: 바운딩 박스 (x0, y0, x1, y1)
        role: 텍스트 역할 (title, heading, body, bullet 등)

        # PDF Layer 전용 (OCR은 None)
        font: 폰트 정보
        line_colors: 라인별 색상 (multi-color 렌더링용)
        line_texts: 라인별 텍스트
        prefix_width: prefix 너비 (bullet 등)
        has_multi_color: multi-color 영역 여부
        expand_allowed: bbox 확장 허용 여부
        keep_prefix: prefix 유지 여부

        # OCR 전용 (PDF Layer는 None)
        confidence: OCR 신뢰도 (0.0 ~ 1.0)
    """
    # 필수 필드
    block_id: str
    source: Literal["pdf", "ocr"]
    page: int
    text: str
    bbox: tuple[float, float, float, float]
    role: str = "body"

    # PDF Layer 전용
    font: Optional[FontInfo] = None
    line_colors: list[int] = field(default_factory=list)
    line_texts: list[str] = field(default_factory=list)
    prefix_width: float = 0.0
    has_multi_color: bool = False
    expand_allowed: bool = True
    keep_prefix: bool = False
    redaction_fill_color: tuple[float, float, float] = (1, 1, 1)

    # OCR 전용
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        """dict 변환 (기존 translations 형식 호환)"""
        d = {
            "block_id": self.block_id,
            "source": self.source,
            "page_num": self.page,
            "text": self.text,
            "original": self.text,  # 기존 호환성
            "bbox": list(self.bbox),
            "role": self.role,
            "prefix_width": self.prefix_width,
            "has_multi_color": self.has_multi_color,
            "expand_allowed": self.expand_allowed,
            "keep_prefix": self.keep_prefix,
            "line_colors": self.line_colors,
            "line_texts": self.line_texts,
            "redaction_fill_color": list(self.redaction_fill_color),
        }

        if self.font:
            d["font"] = self.font.name
            d["size"] = self.font.size
            d["color"] = self.font.color

        if self.confidence is not None:
            d["confidence"] = self.confidence

        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TextBlock":
        """dict에서 생성"""
        font = None
        if d.get("font") or d.get("size") or d.get("color"):
            font = FontInfo(
                name=d.get("font", ""),
                size=d.get("size", 12.0),
                color=d.get("color", 0),
            )

        bbox = d.get("bbox", (0, 0, 0, 0))
        if isinstance(bbox, list):
            bbox = tuple(bbox)

        redaction_fill = d.get("redaction_fill_color", (1, 1, 1))
        if isinstance(redaction_fill, list):
            redaction_fill = tuple(redaction_fill)

        return cls(
            block_id=d.get("block_id", ""),
            source=d.get("source", "pdf"),
            page=d.get("page_num", d.get("page", 0)),
            text=d.get("text", d.get("original", "")),
            bbox=bbox,
            role=d.get("role", "body"),
            font=font,
            line_colors=d.get("line_colors", []),
            line_texts=d.get("line_texts", []),
            prefix_width=d.get("prefix_width", 0.0),
            has_multi_color=d.get("has_multi_color", False),
            expand_allowed=d.get("expand_allowed", True),
            keep_prefix=d.get("keep_prefix", False),
            redaction_fill_color=redaction_fill,
            confidence=d.get("confidence"),
        )

    def with_translation(self, translated: str) -> dict:
        """번역 결과를 포함한 dict 반환 (apply용)"""
        d = self.to_dict()
        d["translated"] = translated
        return d


@dataclass
class TranslationResult:
    """번역 결과

    translate_blocks()의 반환값
    """
    translations: dict[str, str]  # block_id → 번역문
    failed_ids: list[str] = field(default_factory=list)  # 번역 실패한 block_id

    def get(self, block_id: str, default: str = "") -> str:
        """번역 결과 조회 (없으면 default)"""
        return self.translations.get(block_id, default)

    def __len__(self) -> int:
        return len(self.translations)
