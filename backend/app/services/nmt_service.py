"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역

우선순위:
1. CTranslate2 (models/opus-mt-ct2/ 존재 시) — CPU 3~5배 가속, int8 양자화
2. HuggingFace transformers 폴백 — ctranslate2 미설치 또는 변환 전 상태
"""
import subprocess
from pathlib import Path

from app.config import resolve_model_dir, USER_DATA_DIR


def _ct2_model_dir() -> Path:
    """CT2 변환된 모델 디렉토리. resolve_model_dir로 동봉/사용자/프로젝트 검색,
    없으면 USER_DATA_DIR/models/opus-mt-ct2/ (변환 결과 저장 위치)."""
    found = resolve_model_dir("opus-mt-ct2")
    return found if found is not None else USER_DATA_DIR / "models" / "opus-mt-ct2"


class NMTService:
    def __init__(self, model_name: str = "Helsinki-NLP/opus-mt-ko-en", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = "cuda" if device in ("cuda", "cuda:0") else "cpu"
        self.dtype = dtype
        self._mode = None  # "ct2" | "hf"

        # CT2 → HF 순으로 시도
        if self._try_load_ct2():
            self._mode = "ct2"
        else:
            self._load_hf()
            self._mode = "hf"

    # ── CTranslate2 ─────────────────────────────────────────────────────────

    def _try_load_ct2(self) -> bool:
        try:
            import ctranslate2  # noqa: F401
        except ImportError:
            print("[NMT] ctranslate2 미설치 → HuggingFace 폴백 (npm run setup으로 설치 가능)")
            return False

        try:
            import ctranslate2
            import sentencepiece as spm

            ct2_dir = _ct2_model_dir()
            if not ct2_dir.exists():
                self._convert_model(ct2_dir)

            self._ct2 = ctranslate2.Translator(
                str(ct2_dir),
                device=self.device,
                inter_threads=2,
            )
            self._sp_src = spm.SentencePieceProcessor()
            self._sp_src.Load(str(ct2_dir / "source.spm"))
            self._sp_tgt = spm.SentencePieceProcessor()
            self._sp_tgt.Load(str(ct2_dir / "target.spm"))

            print(f"[NMT] CTranslate2 opus-mt-ko-en 로드 완료 ({self.device}, int8) [{ct2_dir}]")
            return True
        except Exception as e:
            print(f"[NMT] CTranslate2 로드 실패 → HuggingFace 폴백: {e}")
            return False

    def _convert_model(self, ct2_dir: Path):
        print(f"[NMT] CTranslate2 변환 중: {self.model_name} → {ct2_dir}")
        ct2_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ct2-transformers-converter",
                "--model", self.model_name,
                "--output_dir", str(ct2_dir),
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
            self._hf_tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._hf_model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_name,
                torch_dtype=self._torch_dtype(),
                device_map=self.device,
            )
            self._hf_model.eval()
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
        if not text.strip():
            return ""
        try:
            if self._mode == "ct2":
                return self._translate_ct2(text)
            else:
                return self._translate_hf(text, max_length)
        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return ""

    def _translate_ct2(self, text: str) -> str:
        tokens = self._sp_src.Encode(text, out_type=str)
        # 곱수 2.5(긴 문장 잘림 방지 더 여유) + floor 20
        max_decoding_length = max(20, int(len(tokens) * 2.5))
        results = self._ct2.translate_batch(
            [tokens],
            max_decoding_length=max_decoding_length,
            beam_size=2,                # beam search 활성화
            length_penalty=1.0,         # 중립 — 0.6은 긴 번역 자르는 부작용
            repetition_penalty=2.0,
            no_repeat_ngram_size=2,
        )
        return self._sp_tgt.Decode(results[0].hypotheses[0]).strip()

    def _translate_hf(self, text: str, max_length: int) -> str:
        import torch
        inputs = self._hf_tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        # CT2 경로와 동일 정책 — 곱수 2.5 + floor 20
        adjusted_max = min(max_length, max(20, int(inputs["input_ids"].shape[1] * 2.5)))
        with torch.no_grad():
            outputs = self._hf_model.generate(
                **inputs,
                max_length=adjusted_max,
                num_beams=2,
                length_penalty=1.0,
                repetition_penalty=2.0,
                no_repeat_ngram_size=2,
            )
        return self._hf_tokenizer.decode(outputs[0], skip_special_tokens=True).strip()

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
