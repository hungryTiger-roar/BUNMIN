"""
LLM Client Integration

[역할]
- 다양한 LLM 백엔드 지원 (OpenAI, Gemini 등)
- 통일된 인터페이스 제공
- 에러 핸들링 및 재시도 로직

[호출 경로]
pdf_layer_pipeline.py → llm_client.py (이 파일)

[주요 클래스]
- BaseLLMClient: 추상 기본 클래스
- OpenAIClient: OpenAI GPT 클라이언트
- GeminiClient: Google Gemini 클라이언트

[주요 함수]
- get_default_llm_client(): 환경변수 기반 기본 클라이언트 반환
"""
import os
from abc import ABC, abstractmethod
from typing import Optional, Any


class BaseLLMClient(ABC):
    """LLM 클라이언트 기본 인터페이스"""

    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        """프롬프트에 대한 응답 생성

        Args:
            prompt: 입력 프롬프트
            **kwargs: 추가 파라미터 (temperature, max_tokens 등)

        Returns:
            생성된 텍스트
        """
        pass

    @abstractmethod
    def complete_chat(self, messages: list[dict], **kwargs) -> str:
        """채팅 형식 응답 생성

        Args:
            messages: [{"role": "user/assistant/system", "content": "..."}]
            **kwargs: 추가 파라미터

        Returns:
            생성된 텍스트
        """
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI API 클라이언트"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        default_temperature: float = 0.3,
        default_max_tokens: int = 4096,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self._client = None

    def _get_client(self):
        """클라이언트 lazy 초기화"""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            except ImportError:
                raise ImportError("openai 패키지가 필요합니다: pip install openai")

        return self._client

    def complete(self, prompt: str, **kwargs) -> str:
        """단일 프롬프트 완성"""
        messages = [{"role": "user", "content": prompt}]
        return self.complete_chat(messages, **kwargs)

    def complete_chat(self, messages: list[dict], **kwargs) -> str:
        """채팅 완성"""
        client = self._get_client()

        temperature = kwargs.get("temperature", self.default_temperature)
        max_tokens = kwargs.get("max_tokens", self.default_max_tokens)
        model = kwargs.get("model", self.model)

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content


class AzureOpenAIClient(BaseLLMClient):
    """Azure OpenAI API 클라이언트"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        deployment_name: str = "gpt-4o-mini",
        api_version: str = "2024-02-15-preview",
        default_temperature: float = 0.3,
        default_max_tokens: int = 4096,
    ):
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment_name = deployment_name
        self.api_version = api_version
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self._client = None

    def _get_client(self):
        """클라이언트 lazy 초기화"""
        if self._client is None:
            try:
                from openai import AzureOpenAI
                self._client = AzureOpenAI(
                    api_key=self.api_key,
                    azure_endpoint=self.endpoint,
                    api_version=self.api_version,
                )
            except ImportError:
                raise ImportError("openai 패키지가 필요합니다: pip install openai")

        return self._client

    def complete(self, prompt: str, **kwargs) -> str:
        """단일 프롬프트 완성"""
        messages = [{"role": "user", "content": prompt}]
        return self.complete_chat(messages, **kwargs)

    def complete_chat(self, messages: list[dict], **kwargs) -> str:
        """채팅 완성"""
        client = self._get_client()

        temperature = kwargs.get("temperature", self.default_temperature)
        max_tokens = kwargs.get("max_tokens", self.default_max_tokens)

        response = client.chat.completions.create(
            model=self.deployment_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content


class LocalLLMClient(BaseLLMClient):
    """로컬 LLM 클라이언트 (HuggingFace, vLLM 등)"""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-7B-Instruct",
        device: str = "cuda",
        default_temperature: float = 0.3,
        default_max_tokens: int = 4096,
    ):
        self.model_name = model_name
        self.device = device
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """모델 lazy 로딩"""
        if self._model is None:
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                import torch

                self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=torch.float16,
                    device_map="auto",
                )
            except ImportError:
                raise ImportError("transformers 패키지가 필요합니다: pip install transformers")

        return self._model, self._tokenizer

    def complete(self, prompt: str, **kwargs) -> str:
        """단일 프롬프트 완성"""
        model, tokenizer = self._load_model()

        max_tokens = kwargs.get("max_tokens", self.default_max_tokens)
        temperature = kwargs.get("temperature", self.default_temperature)

        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            pad_token_id=tokenizer.eos_token_id,
        )

        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        # 입력 부분 제거
        return response[len(prompt):].strip()

    def complete_chat(self, messages: list[dict], **kwargs) -> str:
        """채팅 완성 (프롬프트로 변환)"""
        model, tokenizer = self._load_model()

        # 채팅 템플릿 적용
        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
        else:
            # 수동 포맷팅
            prompt = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                prompt += f"{role}: {content}\n"
            prompt += "assistant: "

        return self.complete(prompt, **kwargs)


class MockLLMClient(BaseLLMClient):
    """테스트용 Mock LLM 클라이언트"""

    def __init__(self, default_response: str = ""):
        self.default_response = default_response
        self.call_history = []

    def complete(self, prompt: str, **kwargs) -> str:
        """Mock 응답"""
        self.call_history.append({"type": "complete", "prompt": prompt, "kwargs": kwargs})
        return self.default_response

    def complete_chat(self, messages: list[dict], **kwargs) -> str:
        """Mock 채팅 응답"""
        self.call_history.append({"type": "chat", "messages": messages, "kwargs": kwargs})
        return self.default_response


def create_llm_client(
    provider: str = "openai",
    **kwargs
) -> BaseLLMClient:
    """LLM 클라이언트 팩토리

    Args:
        provider: "openai" | "azure" | "local" | "mock"
        **kwargs: 클라이언트별 파라미터

    Returns:
        BaseLLMClient 구현체
    """
    if provider == "openai":
        return OpenAIClient(**kwargs)
    elif provider == "azure":
        return AzureOpenAIClient(**kwargs)
    elif provider == "local":
        return LocalLLMClient(**kwargs)
    elif provider == "mock":
        return MockLLMClient(**kwargs)
    else:
        raise ValueError(f"지원하지 않는 LLM provider: {provider}")


def get_default_llm_client() -> Optional[BaseLLMClient]:
    """환경 변수 기반 기본 LLM 클라이언트 생성"""
    # dotenv 로드 시도
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Azure 우선 체크
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        print("[LLMClient] Azure OpenAI 클라이언트 생성")
        return create_llm_client("azure")

    # OpenAI 체크
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        print(f"[LLMClient] OpenAI 클라이언트 생성 (key: {api_key[:10]}...)")
        return create_llm_client("openai")

    # 기본값 없음
    return None
