"""
NMT (Neural Machine Translation) 서비스
한국어 → 영어 번역
"""
from typing import Optional


class NMTService:
    """
    기계 번역 서비스

    CPU: Helsinki-NLP/opus-mt-ko-en
    GPU: facebook/nllb-200-distilled-600M
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.is_nllb = "nllb" in model_name.lower()
        self._load_model()

    def _load_model(self):
        """모델 로드"""
        try:
            from transformers import AutoModelForSeq2SeqLM, MarianTokenizer, AutoTokenizer
            import torch

            # Marian 모델 (OPUS-MT)은 MarianTokenizer 사용
            if "opus-mt" in self.model_name.lower() or "marian" in self.model_name.lower():
                self.tokenizer = MarianTokenizer.from_pretrained(self.model_name)
            else:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)

            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float16 if "cuda" in self.device else torch.float32,
            )

            if "cuda" in self.device:
                self.model = self.model.to(self.device)

            self.model.eval()
            print(f"[NMT] {self.model_name} 모델 로드 완료")

        except ImportError:
            raise RuntimeError("Transformers가 설치되지 않았습니다")

    def translate(
        self,
        text: str,
        source_lang: str = "ko",
        target_lang: str = "en",
        max_length: int = 512,
    ) -> str:
        """
        텍스트 번역

        Args:
            text: 번역할 텍스트
            source_lang: 원본 언어
            target_lang: 대상 언어
            max_length: 최대 출력 길이

        Returns:
            번역된 텍스트
        """
        if self.model is None or not text.strip():
            return ""

        try:
            import torch

            # NLLB 모델은 언어 코드가 다름
            if self.is_nllb:
                # NLLB 언어 코드: kor_Hang (한국어), eng_Latn (영어)
                self.tokenizer.src_lang = "kor_Hang"
                forced_bos_token_id = self.tokenizer.convert_tokens_to_ids("eng_Latn")
            else:
                forced_bos_token_id = None

            # 토큰화
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_length,
            )

            if "cuda" in self.device:
                inputs = {k: v.to(self.device) for k, v in inputs.items()}

            # 번역 생성
            with torch.no_grad():
                generate_kwargs = {
                    "max_length": max_length,
                    "num_beams": 4,
                    "early_stopping": True,
                }
                if forced_bos_token_id:
                    generate_kwargs["forced_bos_token_id"] = forced_bos_token_id

                outputs = self.model.generate(**inputs, **generate_kwargs)

            # 디코딩
            translated = self.tokenizer.decode(
                outputs[0], skip_special_tokens=True
            )

            return translated.strip()

        except Exception as e:
            print(f"[NMT] 번역 오류: {e}")
            return text

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "ko",
        target_lang: str = "en",
    ) -> list[str]:
        """
        여러 텍스트 일괄 번역

        Args:
            texts: 번역할 텍스트 리스트
            source_lang: 원본 언어
            target_lang: 대상 언어

        Returns:
            번역된 텍스트 리스트
        """
        if not texts:
            return []

        try:
            import torch

            # 빈 텍스트 필터링
            valid_texts = [t for t in texts if t.strip()]
            if not valid_texts:
                return [""] * len(texts)

            inputs = self.tokenizer(
                valid_texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )

            if self.device == "cuda":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_length=512,
                    num_beams=4,
                    early_stopping=True,
                )

            translated = self.tokenizer.batch_decode(
                outputs, skip_special_tokens=True
            )

            # 원래 순서대로 결과 매핑
            result = []
            valid_idx = 0
            for text in texts:
                if text.strip():
                    result.append(translated[valid_idx].strip())
                    valid_idx += 1
                else:
                    result.append("")

            return result

        except Exception as e:
            print(f"[NMT] 배치 번역 오류: {e}")
            return texts
