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
        # 도메인 용어 inline 치환 (활성화된 경우만) — NLLB 가 영어 부분을 통과시킴
        normalized = self._apply_glossary_inline(normalized)
        try:
            if self._mode == "ct2":
                return self._translate_ct2(normalized).strip()
            else:
                return self._translate_hf(normalized, max_length).strip()
        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return ""

    def _translate_ct2(self, text: str) -> str:
        # NLLB 토크나이저 → 토큰 ID → 토큰 문자열 (CT2 입력 형식)
        # src_lang 으로 한국어 prefix 자동 부여, EOS 자동 부여
        input_ids = self._tokenizer(text, return_tensors=None).input_ids
        src_tokens = self._tokenizer.convert_ids_to_tokens(input_ids)

        # NLLB 는 길이 비례 출력이 안정적이라 2.0배면 충분 (opus-mt 의 2.5배 → 절감)
        max_decoding_length = max(len(src_tokens) + 5, int(len(src_tokens) * 2.0))
        results = self._ct2.translate_batch(
            [src_tokens],
            target_prefix=[[_NLLB_TGT_LANG]],   # 디코더 첫 토큰으로 타겟 언어 지정 필수
            max_decoding_length=max_decoding_length,
            beam_size=4,
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
        adjusted_max = min(max_length, max(input_len + 5, int(input_len * 2.0)))
        with torch.no_grad():
            outputs = self._hf_model.generate(
                **inputs,
                forced_bos_token_id=self._hf_tgt_id,   # NLLB 타겟 언어 강제
                max_length=adjusted_max,
                num_beams=4,
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
