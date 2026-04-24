"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역
- NLLB 계열: AutoModelForSeq2SeqLM (facebook/nllb-*)
"""


class NMTService:
    _LANG_MAP = {
        "ko": "kor_Hang",
        "en": "eng_Latn",
        "zh": "zho_Hans",
        "ja": "jpn_Jpan",
    }

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-1.3B", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = "cuda:0" if device == "cuda" else device
        self.dtype = dtype
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _torch_dtype(self):
        import torch
        return {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(self.dtype, torch.float32)

    def _load_model(self):
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_name,
                dtype=self._torch_dtype(),
                device_map=self.device,
            )
            self.model.eval()
            print(f"[NMT] {self.model_name} 로드 완료 ({self.dtype}, {self.device})")
        except ImportError as e:
            raise RuntimeError(f"필요한 패키지가 설치되지 않았습니다: {e}")

    def translate(
        self,
        text: str,
        source_lang: str = "ko",
        target_lang: str = "en",
        max_length: int = 512,
    ) -> str:
        if self.model is None or not text.strip():
            return ""
        try:
            import torch
            src = self._LANG_MAP.get(source_lang, "kor_Hang")
            tgt = self._LANG_MAP.get(target_lang, "eng_Latn")

            self.tokenizer.src_lang = src
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            tgt_lang_id = self.tokenizer.convert_tokens_to_ids(tgt)
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    forced_bos_token_id=tgt_lang_id,
                    max_length=max_length,
                )
            return self.tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return ""

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
