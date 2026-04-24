"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역
- NLLB 계열: AutoModelForSeq2SeqLM (facebook/nllb-*)
- HY-MT 계열: AutoModelForCausalLM + chat template (tencent/HY-MT*)
"""


def _normalize_device(device: str) -> str:
    return "cuda:0" if device == "cuda" else device


def _is_causal_lm(model_name: str) -> bool:
    return "HY-MT" in model_name or "hymt" in model_name.lower()


class NMTService:
    _NLLB_LANG_MAP = {
        "ko": "kor_Hang",
        "en": "eng_Latn",
        "zh": "zho_Hans",
        "ja": "jpn_Jpan",
    }
    _CAUSAL_LANG_MAP = {
        "en": "English",
        "ko": "Korean",
        "zh": "Chinese",
        "ja": "Japanese",
    }

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-1.3B", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = _normalize_device(device)
        self.dtype = dtype
        self.model = None
        self.tokenizer = None
        self._causal = _is_causal_lm(model_name)
        self._load_model()

    def _torch_dtype(self):
        import torch
        return {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(self.dtype, torch.float32)

    def _load_model(self):
        try:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=True
            )

            if self._causal:
                from transformers import AutoModelForCausalLM
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=self._torch_dtype(),
                    device_map=self.device,
                    trust_remote_code=True,
                )
            else:
                from transformers import AutoModelForSeq2SeqLM
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
        context: str = "",
    ) -> str:
        if self.model is None or not text.strip():
            return ""
        try:
            if self._causal:
                return self._translate_causal(text, target_lang, max_length, context)
            else:
                return self._translate_seq2seq(text, source_lang, target_lang, max_length, context)
        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return ""

    def _translate_causal(self, text: str, target_lang: str, max_length: int, context: str = "") -> str:
        import torch
        tgt = self._CAUSAL_LANG_MAP.get(target_lang, "English")
        context_block = f"Slide content for context:\n{context[:300]}\n\n" if context.strip() else ""
        messages = [{
            "role": "user",
            "content": f"{context_block}Translate the following segment into {tgt}, without additional explanation.\n\n{text}",
        }]
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = {k: v.to(self.device) for k, v in self.tokenizer(prompt, return_tensors="pt").items() if k != "token_type_ids"}
        input_len = inputs["input_ids"].shape[1]
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_length,
                top_k=20,
                top_p=0.6,
                repetition_penalty=1.05,
                temperature=0.7,
            )
        return self.tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True).strip()

    def _translate_seq2seq(self, text: str, source_lang: str, target_lang: str, max_length: int, context: str = "") -> str:
        import torch
        src = self._NLLB_LANG_MAP.get(source_lang, "kor_Hang")
        tgt = self._NLLB_LANG_MAP.get(target_lang, "eng_Latn")

        # NLLB는 seq2seq 모델 — 입력 전체를 번역하므로 컨텍스트를 텍스트로 붙이면 안 됨
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
