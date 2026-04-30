"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역

우선순위:
1. CTranslate2 (models/opus-mt-ko-en-ct2/ 존재 시) — CPU 3~5배 가속, int8 양자화
2. HuggingFace transformers 폴백 — ctranslate2 미설치 또는 변환 전 상태
"""
import re
import subprocess
from pathlib import Path

_MODELS_ROOT = Path(__file__).parent.parent.parent.parent / "models"


def _ct2_model_dir(model_name: str) -> Path:
    # "Helsinki-NLP/opus-mt-tc-big-ko-en" → "models/opus-mt-tc-big-ko-en-ct2"
    return _MODELS_ROOT / (model_name.split("/")[-1] + "-ct2")


# 대학교 강의 맥락: 관사·접속사·조동사는 정상적으로 반복되므로 반복 감지 제외
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
    'and', 'or', 'but', 'not', 'so', 'if', 'it', 'this', 'that',
    'you', 'we', 'i', 'do', 'can', 'will', 'have', 'has', 'had', 'just',
    'how', 'what', 'when', 'where', 'who', 'which', 'about',
})


def _postprocess_translation(text: str) -> str:
    """opus-mt 반복 생성 제거:
    1) 문장 경계 이후 추가 생성된 내용 제거
    2) 동일 어간 단어가 세 번 등장하면 첫 반복 직전까지만 반환 (기술 용어 정상 반복 허용)
    """
    text = text.strip()

    # 1) 첫 완성 문장 이후 내용 제거 ("How are you? How are..." → "How are you?")
    m = re.match(r'^(.+?[.!?])\s+\S', text)
    if m:
        return m.group(1)

    # 2) 단어 반복 감지 — stop word 제외, 동일 어간이 세 번째 등장 시 그 전까지만 반환
    words = text.split()
    seen: dict[str, int] = {}
    for i, w in enumerate(words):
        stem = re.sub(r'[^a-z]', '', w.lower())  # 구두점·대소문자 제거
        if not stem or stem in _STOP_WORDS:
            continue
        seen[stem] = seen.get(stem, 0) + 1
        if seen[stem] >= 3:
            truncated = ' '.join(words[:i]).rstrip(',.;')
            if truncated:
                return truncated + '.'
            break

    return text


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

            ct2_dir = _ct2_model_dir(self.model_name)
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

            print(f"[NMT] CTranslate2 {self.model_name} 로드 완료 ({self.device}, int8)")
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
        from huggingface_hub import hf_hub_download
        for spm in ["source.spm", "target.spm"]:
            hf_hub_download(
                repo_id=self.model_name,
                filename=spm,
                local_dir=str(ct2_dir),
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
        normalized = text.strip()
        if not normalized:
            return ""
        try:
            if self._mode == "ct2":
                result = self._translate_ct2(normalized)
            else:
                result = self._translate_hf(normalized, max_length)
            return _postprocess_translation(result)
        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return ""

    def _translate_ct2(self, text: str) -> str:
        tokens = self._sp_src.Encode(text, out_type=str)
        # floor를 입력 길이 기준으로 — 절댓값 20은 짧은 입력에서 hallucination 유발
        # 영어 학술 문장은 한국어보다 길어지므로 2.5x 여유 확보
        max_decoding_length = max(len(tokens) + 5, int(len(tokens) * 2.5))
        # 짧은 입력(≤6토큰)은 greedy — beam search가 대소문자 변형 반복 토큰을 선택하는 문제 방지
        beam_size = 1 if len(tokens) <= 6 else 4
        results = self._ct2.translate_batch(
            [tokens],
            max_decoding_length=max_decoding_length,
            beam_size=beam_size,
            length_penalty=1.0,
            # 2.5: 기술 용어 정상 반복을 허용하면서 hallucination 억제 (3.0은 과도하게 억제)
            repetition_penalty=2.5,
            no_repeat_ngram_size=3,
        )
        return self._sp_tgt.Decode(results[0].hypotheses[0]).strip()

    def _translate_hf(self, text: str, max_length: int) -> str:
        import torch
        inputs = self._hf_tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]
        adjusted_max = min(max_length, max(input_len + 5, int(input_len * 2.5)))
        num_beams = 1 if input_len <= 6 else 4
        with torch.no_grad():
            outputs = self._hf_model.generate(
                **inputs,
                max_length=adjusted_max,
                num_beams=num_beams,
                length_penalty=1.0,
                repetition_penalty=2.5,
                no_repeat_ngram_size=3,
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
