"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역

기본 모델: facebook/nllb-200-distilled-600M
  - 200개 언어 다국어 transformer (Meta)
  - 짧은 인사말 / 구두점 없는 다문장에서도 환각 거의 없음
  - CT2 int8 변환본 ~600MB

우선순위:
1. CTranslate2 (models/<name>-ct2/ 존재 시) — CPU 가속, int8 양자화
2. HuggingFace transformers 폴백 — ctranslate2 미설치 또는 변환 전 상태
"""
import re
import subprocess
from pathlib import Path

from app.config import resolve_model_dir, PROJECT_ROOT, USER_DATA_DIR


# NLLB FLORES-200 언어 코드 — 입력/출력에 명시해야 NLLB 가 정확히 번역
_NLLB_SRC_LANG = "kor_Hang"   # 한국어 한글 표기
_NLLB_TGT_LANG = "eng_Latn"   # 영어 라틴 표기


# ── NLLB 환각 필터 ─────────────────────────────────────────────────────────────
# NLLB-200 distilled 600M 은 학습 데이터 (commoncrawl 의 K-드라마 팬자막 / Amara.org /
# YouTube 자막) 에서 "한글자막 by [이름]", "Subtitles by Amara.org", "Thanks for watching"
# 같은 정형 텍스트를 학습. ASR 잔재 ("어어", "음") / 짧은 입력 / 반복 음절 등이 들어오면
# 이 텍스트를 그대로 토해내는 환각 발생. 두 단계로 차단:
#   1) 입력 게이트: 환각 트리거 입력은 NMT 호출 자체 skip (성능 절감 + 환각 차단)
#   2) 출력 필터: 정상 입력에서도 가끔 새는 환각을 패턴 매치로 차단 → 빈 문자열 반환
#
# 참고: "감사합니다" / "Thank you" 단독 출현은 대부분 ASR 단의 silence-환각이 NMT 를
# 정상 통과한 캐스케이드 결과 (asr_service.py 의 ⑤·⑦ 필터에서 차단). MT 단 한국어
# passthrough 환각은 이론상 가능하지만 실제 관측 거의 없음 → target_lang 미스매치 +
# 한국어 정형 패턴 (시청해주셔서, 구독과 좋아요) 만 backup 으로 유지.

# 정확히 "정형 환각 텍스트" 만 잡도록 좁게 작성 (false positive 최소화 — 강의 본문에서
# "자막", "MBC" 같은 단어 단독 등장은 통과시킴)
_HALLUCINATION_PATTERNS = [
    # A. 한국 자막 크레딧 — "한글자막 by 한효정" 등
    re.compile(r'한[국글]\s*(어\s*)?자막\s*(by|제작|번역|제공|:)', re.IGNORECASE),
    re.compile(r'자막\s*(제작|번역)\s*[:by]', re.IGNORECASE),
    re.compile(r'(번역|자막)\s*by\s+\S+', re.IGNORECASE),

    # B. 영어 자막 / 전사 크레딧
    re.compile(r'\b(subtitles?|translation|transcribed)\s+by\b', re.IGNORECASE),
    re.compile(r'\b(amara\.org|otter\.ai|castingwords)\b', re.IGNORECASE),

    # C. YouTube 시청 권유 (한국어 / 영어)
    re.compile(r'시청해\s*주(셔서|시는)'),
    re.compile(r'구독과?\s*좋아요'),
    re.compile(r'\bthanks?\s+(for|to)\s+watching\b', re.IGNORECASE),
    re.compile(r'\bplease\s+subscribe\b', re.IGNORECASE),
    re.compile(r'\blike\s+and\s+subscribe\b', re.IGNORECASE),

    # C-2. 단독 "Thank you" 환각 — "감사합니다" 가 silence-phrase 가드를 metric
    # 좋아서 통과한 후 NMT 가 standalone "Thank you" 로 번역. 학생 화면에 강사가
    # 안 한 인사 음성이 송출되는 치명 케이스 차단. ^...$ 앵커로 단독 매칭만 —
    # "thank you for asking" 같은 정상 문맥 통과.
    re.compile(r'^\s*thank\s*you\s*[\.!\?…]?\s*$', re.IGNORECASE),

    # D. 자막 메타 / 포맷 누설
    re.compile(r'^\s*WEBVTT\b'),
    re.compile(r'^\s*\d{2}:\d{2}:\d{2}[,\.]?\d*'),
    re.compile(r'^\s*[\(\[]\s*(음악|박수|웃음|효과음|BGM|MUSIC|APPLAUSE|LAUGHTER)\s*[\)\]]\s*$',
               re.IGNORECASE),

    # E. URL 워터마크
    re.compile(r'www\.\w+\.(org|com|co\.kr)\b'),
]


def _is_hallucination_trigger(text: str) -> bool:
    """입력 게이트 — 환각 유발 가능성이 높은 ASR 결과를 사전 차단.
    True 반환 시 NMT 호출 skip → 빈 문자열 반환.
    """
    s = text.strip()
    if len(s) < 3:
        return True                                     # 너무 짧음 ("어", "음")
    if re.fullmatch(r'[\d\s\.\,\?\!\-…]+', s):
        return True                                     # 숫자/기호만 ("1.", "...")
    if re.search(r'(.)\1{3,}', s):
        return True                                     # 같은 문자 4회+ 연속 ("그그그그")
    korean_chars = sum(1 for c in s if '가' <= c <= '힯')
    if korean_chars < 2:
        return True                                     # 한글 의미 토큰 부족
    return False


def _is_hallucination_output(
    text: str,
    target_lang: str = "en",
    glossary_terms: set[str] | None = None,
) -> bool:
    """출력 필터 — NMT 결과가 알려진 환각 패턴인지 검사.

    glossary_terms: NMT 가 보호해야 하는 도메인 용어 (예: 'BERT', 'GIST').
    출력에 이 용어가 포함된 한국어-우세 문장은 환각이 아니라 NMT 의 부분 미번역으로
    간주하고 통과시킴 (예: "BERT는 양방향 인코더" — 정상 의미 있음).
    """
    if not text:
        return False
    # 반복 루핑 — 같은 단어 4회+ 연속 ("yes yes yes yes" / "네 네 네 네")
    tokens = text.split()
    if len(tokens) >= 4:
        for i in range(len(tokens) - 3):
            if tokens[i] == tokens[i+1] == tokens[i+2] == tokens[i+3]:
                return True
    # 타겟 언어 미스매치 — eng_Latn 강제했는데 한국어가 영어보다 많으면 환각.
    # "감사합니다" / "한글자막 by 한효정" 같이 source 가 그대로 새는 케이스 직격.
    # 단, glossary 보호 단어가 출력에 있으면 NMT 부분 미번역으로 보고 면제.
    if target_lang == "en":
        korean = sum(1 for c in text if '가' <= c <= '힯')
        latin = sum(1 for c in text if c.isascii() and c.isalpha())
        if korean > 0 and korean >= latin:
            if glossary_terms and any(t in text for t in glossary_terms):
                return False
            return True
    return any(p.search(text) for p in _HALLUCINATION_PATTERNS)


def _ct2_model_dir(model_name: str) -> Path:
    """CT2 변환된 모델 디렉토리.
    "facebook/nllb-200-distilled-600M" → "{name}-ct2" 형태로 매핑.
    USER_DATA_DIR / INSTALL_DIR / PROJECT_ROOT 다단계 폴백 (Electron 배포 호환),
    어디에도 없으면 frozen 시 USER_DATA_DIR, dev 시 PROJECT_ROOT 아래 새로 만듦.
    """
    name = model_name.split("/")[-1] + "-ct2"
    found = resolve_model_dir(name)
    if found is not None:
        return found
    base = USER_DATA_DIR if USER_DATA_DIR.exists() and not (PROJECT_ROOT / "models").exists() else PROJECT_ROOT
    return base / "models" / name


class NMTService:
    def __init__(self, model_name: str = "facebook/nllb-200-distilled-600M", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = "cuda" if device in ("cuda", "cuda:0") else "cpu"
        self.dtype = dtype
        self._mode = None  # "ct2" | "hf"
        # 도메인 용어집 — 강의 시작 시 set_glossary() 로 주입됨.
        # 길이 내림차순 정렬된 (한글, 영어) 튜플 리스트로 관리해 긴 용어 우선 매치 ("자연어 처리"가 "자연어"보다 먼저).
        self._glossary_pairs: list[tuple[str, str]] = []

        # CT2 → HF 순으로 시도
        if self._try_load_ct2():
            self._mode = "ct2"
        else:
            self._load_hf()
            self._mode = "hf"

    # ── 도메인 용어집 ────────────────────────────────────────────────────────

    def get_glossary_terms(self) -> tuple[set[str], set[str]]:
        """현재 적용 중인 용어집의 (한국어 set, 영어 set) 반환.
        ws.py 의 ASR 검증 로직 (영어 비중 가드) 이 도메인 용어를 false positive
        에서 제외하는 데 사용. 빈 dict / 미설정이면 빈 set 반환.
        """
        if not self._glossary_pairs:
            return set(), set()
        ko_terms = {ko for ko, _ in self._glossary_pairs}
        en_terms = {en for _, en in self._glossary_pairs}
        return ko_terms, en_terms

    def set_glossary(self, glossary: dict[str, str] | None) -> None:
        """한글 → 영어 도메인 용어 매핑 주입. None / 빈 dict 면 비활성.
        translate() 호출 시 한글 입력에서 매칭되는 용어를 영어로 inline 치환 →
        NLLB sentencepiece 가 영어 토큰을 그대로 통과시키므로 고유명사·약어 보호.
        """
        if not glossary:
            self._glossary_pairs = []
            print("[NMT] 용어집 비활성")
            return
        self._glossary_pairs = sorted(
            ((k, v) for k, v in glossary.items() if k and v),
            key=lambda kv: -len(kv[0]),
        )
        print(f"[NMT] 용어집 적용: {len(self._glossary_pairs)}개")

    def _apply_glossary_inline(self, text: str) -> str:
        """한글 텍스트의 도메인 용어를 영어로 inline 치환.
        NLLB 입력에 영어가 섞여 있으면 그대로 통과되는 특성 활용. 양 옆 공백으로 토큰 경계 보장.
        """
        if not self._glossary_pairs:
            return text
        result = text
        for ko, en in self._glossary_pairs:
            if ko in result:
                result = result.replace(ko, f" {en} ")
        return re.sub(r"\s+", " ", result).strip()

    # ── CTranslate2 ─────────────────────────────────────────────────────────

    def _try_load_ct2(self) -> bool:
        try:
            import ctranslate2  # noqa: F401
        except ImportError:
            print("[NMT] ctranslate2 미설치 → HuggingFace 폴백 (npm run setup으로 설치 가능)")
            return False

        try:
            import ctranslate2
            from transformers import AutoTokenizer

            ct2_dir = _ct2_model_dir(self.model_name)
            if not ct2_dir.exists():
                self._convert_model(ct2_dir)

            self._ct2 = ctranslate2.Translator(
                str(ct2_dir),
                device=self.device,
                inter_threads=2,
            )
            # NLLB 토크나이저 — src_lang 명시로 한국어 prefix 자동 부여
            # ct2-transformers-converter 가 --copy_files 로 동봉한 tokenizer 파일을 사용
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(ct2_dir),
                src_lang=_NLLB_SRC_LANG,
            )

            print(f"[NMT] CTranslate2 {self.model_name} 로드 완료 ({self.device}, int8) [{ct2_dir}]")
            return True
        except Exception as e:
            print(f"[NMT] CTranslate2 로드 실패 → HuggingFace 폴백: {e}")
            return False

    def _convert_model(self, ct2_dir: Path):
        """ct2-transformers-converter 로 NLLB 변환 + 토크나이저 파일 동봉.
        --copy_files 로 tokenizer.json / sentencepiece.bpe.model / special_tokens_map.json /
        tokenizer_config.json 을 함께 복사 → AutoTokenizer.from_pretrained(local_dir) 직접 가능.
        """
        print(f"[NMT] CTranslate2 변환 중: {self.model_name} → {ct2_dir}")
        ct2_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ct2-transformers-converter",
                "--model", self.model_name,
                "--output_dir", str(ct2_dir),
                "--copy_files",
                "tokenizer.json", "sentencepiece.bpe.model",
                "special_tokens_map.json", "tokenizer_config.json",
                "--quantization", "int8",
                "--force",
            ],
            check=True,
        )
        print("[NMT] 변환 완료!")

    # ── HuggingFace 폴백 ─────────────────────────────────────────────────────

    def _torch_dtype(self):
        import torch
        return {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(self.dtype, torch.float32)

    def _load_hf(self):
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            self._hf_tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                src_lang=_NLLB_SRC_LANG,
            )
            self._hf_model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_name,
                torch_dtype=self._torch_dtype(),
                device_map=self.device,
            )
            self._hf_model.eval()
            # NLLB 는 forced_bos_token_id 로 타겟 언어를 지정해야 함
            self._hf_tgt_id = self._hf_tokenizer.convert_tokens_to_ids(_NLLB_TGT_LANG)
            print(f"[NMT] HuggingFace {self.model_name} 로드 완료 ({self.dtype}, {self.device})")
        except ImportError as e:
            raise RuntimeError(f"필요한 패키지가 설치되지 않았습니다: {e}")

    # ── 공통 번역 인터페이스 ─────────────────────────────────────────────────

    def translate(
        self,
        text: str,
        source_lang: str = "ko",
        target_lang: str = "en",
        max_length: int = 512,
    ) -> str:
        normalized = text.strip()
        if not normalized:
            return ""

        # 입력 게이트 — 환각 유발 입력은 NMT 호출 자체 skip (자막 안 뜨고 음성도 안 나옴)
        if _is_hallucination_trigger(normalized):
            print(f"[NMT] 환각 트리거 입력 차단: {normalized!r}")
            return ""

        # 도메인 용어 inline 치환 (활성화된 경우만) — NLLB 가 영어 부분을 통과시킴
        normalized = self._apply_glossary_inline(normalized)
        try:
            if self._mode == "ct2":
                result = self._translate_ct2(normalized).strip()
            else:
                result = self._translate_hf(normalized, max_length).strip()
        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return ""

        # 출력 필터 — 정형 환각 패턴이면 빈 문자열 반환 (다음 발화는 정상 처리됨).
        # glossary 보호 단어 (영어 측) 를 필터에 넘겨 NMT 부분 미번역이 환각으로 오인되지
        # 않게 함 (예: "BERT는 양방향 인코더" — Korean-우세지만 BERT 보호어 있어 통과).
        glossary_en = {en for _, en in self._glossary_pairs} if self._glossary_pairs else None
        if _is_hallucination_output(result, target_lang, glossary_en):
            print(f"[NMT] 환각 출력 차단: {result!r}")
            return ""
        return result

    def _translate_ct2(self, text: str) -> str:
        # NLLB 토크나이저 → 토큰 ID → 토큰 문자열 (CT2 입력 형식)
        # src_lang 으로 한국어 prefix 자동 부여, EOS 자동 부여
        input_ids = self._tokenizer(text, return_tensors=None).input_ids
        src_tokens = self._tokenizer.convert_ids_to_tokens(input_ids)

        # 번역 완전성 우선 — TTS 길이는 1.2배속 + 동적 delay 가 흡수하므로 무리한 단축 안 함.
        #   max_decoding_length: src 2.0배 — 넉넉하게. 영어가 한국어보다 길어도 안 잘림.
        #   length_penalty 1.0: NLLB 기본 — 짧게 끝내려다 긴 한국어 문장 뒷부분이 통째로
        #     누락되는 것(부분 미번역) 차단. 0.8 로 했더니 강의 종료 인사·활동 안내 등이
        #     누락돼 외국인 수강자 이해도 ↓ → 원복.
        #   beam_size 3 (이전 4): 탐색 폭 약간 ↓ → NMT latency -15~25%, 품질 거의 동일 (BLEU -0.2~0.5점)
        max_decoding_length = max(len(src_tokens) + 5, int(len(src_tokens) * 2.0))
        results = self._ct2.translate_batch(
            [src_tokens],
            target_prefix=[[_NLLB_TGT_LANG]],   # 디코더 첫 토큰으로 타겟 언어 지정 필수
            max_decoding_length=max_decoding_length,
            beam_size=3,
            length_penalty=1.0,
            repetition_penalty=1.1,             # NLLB 는 환각 적어서 가벼운 페널티로 충분
        )
        target_tokens = results[0].hypotheses[0]
        # target_prefix 의 eng_Latn 토큰이 출력에 포함될 수 있어 제거
        if target_tokens and target_tokens[0] == _NLLB_TGT_LANG:
            target_tokens = target_tokens[1:]
        target_ids = self._tokenizer.convert_tokens_to_ids(target_tokens)
        return self._tokenizer.decode(target_ids, skip_special_tokens=True)

    def _translate_hf(self, text: str, max_length: int) -> str:
        import torch
        inputs = self._hf_tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]
        # _translate_ct2 와 동일 정책 — src 2.0배 cap (넉넉, 안 잘림), length_penalty 1.0, beam 3
        adjusted_max = min(max_length, max(input_len + 5, int(input_len * 2.0)))
        with torch.no_grad():
            outputs = self._hf_model.generate(
                **inputs,
                forced_bos_token_id=self._hf_tgt_id,   # NLLB 타겟 언어 강제
                max_length=adjusted_max,
                num_beams=3,
                length_penalty=1.0,
                repetition_penalty=1.1,
            )
        return self._hf_tokenizer.decode(outputs[0], skip_special_tokens=True)

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ko",
        target_lang: str = "en",
    ) -> list[str]:
        if not texts:
            return []
        results = []
        total = len(texts)
        for i, t in enumerate(texts, 1):
            results.append(self.translate(t, source_lang, target_lang))
            if total > 1 and (i % 10 == 0 or i == total):
                print(f"  번역 진행: {i}/{total}", flush=True)
        return results
