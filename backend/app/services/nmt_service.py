"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역
tencent/HY-MT1.5-1.8B (AutoModelForCausalLM, GPU: float16 / CPU: float32, chat template)
"""


def _normalize_device(device: str) -> str:
    """'cuda' → 'cuda:0' 정규화"""
    return "cuda:0" if device == "cuda" else device


class NMTService:
    _LANG_MAP = {
        "en": "English",
        "ko": "Korean",
        "zh": "Chinese",
        "ja": "Japanese",
    }

    def __init__(self, model_name: str = "tencent/HY-MT1.5-1.8B", device: str = "cpu", dtype: str = "float32"):
        self.model_name = model_name
        self.device = _normalize_device(device)
        self.dtype = dtype
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _torch_dtype(self):
        import torch
        return {"float16": torch.float16, "bfloat16": torch.bfloat16}.get(self.dtype, torch.float32)

    def _load_model(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=True
            )
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=self._torch_dtype(),
                device_map=self.device,
                trust_remote_code=True,
            )
            self.model.eval()
            print(f"[NMT] {self.model_name} 로드 완료 ({self.dtype}, {self.device})")
        except ImportError:
            raise RuntimeError("Transformers가 설치되지 않았습니다")

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
            tgt = self._LANG_MAP.get(target_lang, "English")
            messages = [{
                "role": "user",
                "content": f"Translate the following segment into {tgt}, without additional explanation.\n\n{text}",
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
            return self.tokenizer.decode(
                outputs[0][input_len:], skip_special_tokens=True
            ).strip()
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
        return [self.translate(t, source_lang, target_lang) for t in texts]
