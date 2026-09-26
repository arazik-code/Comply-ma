"""Multi-provider AI service: OpenAI, Gemini, Claude, Nvidia, Free APIs."""
import json
import logging
import os
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.services.ai")


@dataclass
class AIResponse:
    provider: str
    model: str
    content: str
    tokens_used: int = 0
    latency_ms: int = 0
    success: bool = True
    error: str = ""
    raw: dict = field(default_factory=dict)


class BaseAIProvider(ABC):
    """Base class for AI providers."""
    name: str = "base"
    default_model: str = ""

    @abstractmethod
    def chat(self, prompt: str, model: str = "", system: str = "", **kwargs) -> AIResponse:
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        pass


class OpenAIProvider(BaseAIProvider):
    name = "openai"
    default_model = "gpt-4o"

    def __init__(self):
        self.api_key = settings.ai_openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = settings.ai_openai_base_url or "https://api.openai.com/v1"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, prompt: str, model: str = "", system: str = "", **kwargs) -> AIResponse:
        if not self.is_configured():
            return AIResponse(provider=self.name, model=model, content="", success=False, error="API key not configured")

        model = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages, "temperature": kwargs.get("temperature", 0.7), "max_tokens": kwargs.get("max_tokens", 2000)}

        return self._request(payload, model)

    def _request(self, payload: dict, model: str) -> AIResponse:
        import time
        start = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                content = body["choices"][0]["message"]["content"]
                tokens = body.get("usage", {}).get("total_tokens", 0)
                return AIResponse(provider=self.name, model=model, content=content, tokens_used=tokens, latency_ms=latency, raw=body)
        except Exception as e:
            return AIResponse(provider=self.name, model=model, content="", success=False, error=str(e), latency_ms=int((time.time() - start) * 1000))


class GeminiProvider(BaseAIProvider):
    name = "gemini"
    default_model = "gemini-2.0-flash"

    def __init__(self):
        self.api_key = settings.ai_gemini_api_key or os.getenv("GEMINI_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, prompt: str, model: str = "", system: str = "", **kwargs) -> AIResponse:
        if not self.is_configured():
            return AIResponse(provider=self.name, model=model, content="", success=False, error="API key not configured")

        model = model or self.default_model
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {"contents": contents, "generationConfig": {"temperature": kwargs.get("temperature", 0.7), "maxOutputTokens": kwargs.get("max_tokens", 2000)}}

        return self._request(payload, model)

    def _request(self, payload: dict, model: str) -> AIResponse:
        import time
        start = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                content = body["candidates"][0]["content"]["parts"][0]["text"]
                tokens = body.get("usageMetadata", {}).get("totalTokenCount", 0)
                return AIResponse(provider=self.name, model=model, content=content, tokens_used=tokens, latency_ms=latency, raw=body)
        except Exception as e:
            return AIResponse(provider=self.name, model=model, content="", success=False, error=str(e), latency_ms=int((time.time() - start) * 1000))


class ClaudeProvider(BaseAIProvider):
    name = "claude"
    default_model = "claude-sonnet-4-20250514"

    def __init__(self):
        self.api_key = settings.ai_claude_api_key or os.getenv("ANTHROPIC_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, prompt: str, model: str = "", system: str = "", **kwargs) -> AIResponse:
        if not self.is_configured():
            return AIResponse(provider=self.name, model=model, content="", success=False, error="API key not configured")

        model = model or self.default_model
        payload = {"model": model, "max_tokens": kwargs.get("max_tokens", 2000), "messages": [{"role": "user", "content": prompt}]}
        if system:
            payload["system"] = system

        return self._request(payload, model)

    def _request(self, payload: dict, model: str) -> AIResponse:
        import time
        start = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=data,
                headers={"Content-Type": "application/json", "x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                content = body["content"][0]["text"]
                tokens = body.get("usage", {}).get("input_tokens", 0) + body.get("usage", {}).get("output_tokens", 0)
                return AIResponse(provider=self.name, model=model, content=content, tokens_used=tokens, latency_ms=latency, raw=body)
        except Exception as e:
            return AIResponse(provider=self.name, model=model, content="", success=False, error=str(e), latency_ms=int((time.time() - start) * 1000))


class NvidiaProvider(BaseAIProvider):
    name = "nvidia"
    default_model = "meta/llama-3.1-70b-instruct"

    def __init__(self):
        self.api_key = settings.ai_nvidia_api_key or os.getenv("NVIDIA_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, prompt: str, model: str = "", system: str = "", **kwargs) -> AIResponse:
        if not self.is_configured():
            return AIResponse(provider=self.name, model=model, content="", success=False, error="API key not configured")

        model = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "temperature": kwargs.get("temperature", 0.7), "max_tokens": kwargs.get("max_tokens", 2000), "top_p": 0.7}

        return self._request(payload, model)

    def _request(self, payload: dict, model: str) -> AIResponse:
        import time
        start = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                data=data,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                content = body["choices"][0]["message"]["content"]
                tokens = body.get("usage", {}).get("total_tokens", 0)
                return AIResponse(provider=self.name, model=model, content=content, tokens_used=tokens, latency_ms=latency, raw=body)
        except Exception as e:
            return AIResponse(provider=self.name, model=model, content="", success=False, error=str(e), latency_ms=int((time.time() - start) * 1000))


class FreeAIProvider(BaseAIProvider):
    """Free tier APIs: HuggingFace Inference, Groq (free tier), Together (free tier)."""
    name = "free"
    default_model = "meta-llama/Meta-Llama-3.1-8B-Instruct"

    def __init__(self):
        self.hf_token = settings.ai_hf_token or os.getenv("HF_TOKEN", "")
        self.groq_key = settings.ai_groq_key or os.getenv("GROQ_API_KEY", "")
        self.together_key = settings.ai_together_key or os.getenv("TOGETHER_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.hf_token or self.groq_key or self.together_key)

    def chat(self, prompt: str, model: str = "", system: str = "", **kwargs) -> AIResponse:
        if self.groq_key:
            return self._groq(prompt, model or "llama-3.1-70b-versatile", system, **kwargs)
        if self.together_key:
            return self._together(prompt, model or "meta-llama/Llama-3-70b-chat-hf", system, **kwargs)
        if self.hf_token:
            return self._huggingface(prompt, model or self.default_model, system, **kwargs)
        return AIResponse(provider=self.name, model=model, content="", success=False, error="No free AI API configured")

    def _groq(self, prompt: str, model: str, system: str, **kwargs) -> AIResponse:
        import time
        start = time.time()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "temperature": kwargs.get("temperature", 0.7), "max_tokens": kwargs.get("max_tokens", 2000)}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.groq_key}"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                return AIResponse(provider="free-groq", model=model, content=body["choices"][0]["message"]["content"], tokens_used=body.get("usage", {}).get("total_tokens", 0), latency_ms=latency)
        except Exception as e:
            return AIResponse(provider="free-groq", model=model, content="", success=False, error=str(e))

    def _together(self, prompt: str, model: str, system: str, **kwargs) -> AIResponse:
        import time
        start = time.time()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "temperature": kwargs.get("temperature", 0.7), "max_tokens": kwargs.get("max_tokens", 2000)}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request("https://api.together.xyz/v1/chat/completions", data=data, headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.together_key}"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                return AIResponse(provider="free-together", model=model, content=body["choices"][0]["message"]["content"], tokens_used=body.get("usage", {}).get("total_tokens", 0), latency_ms=latency)
        except Exception as e:
            return AIResponse(provider="free-together", model=model, content="", success=False, error=str(e))

    def _huggingface(self, prompt: str, model: str, system: str, **kwargs) -> AIResponse:
        import time
        start = time.time()
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {"inputs": full_prompt, "parameters": {"max_new_tokens": kwargs.get("max_tokens", 500), "temperature": kwargs.get("temperature", 0.7), "return_full_text": False}}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(f"https://api-inference.huggingface.co/models/{model}", data=data, headers={"Authorization": f"Bearer {self.hf_token}", "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode())
                latency = int((time.time() - start) * 1000)
                content = body[0]["generated_text"] if isinstance(body, list) and body else ""
                return AIResponse(provider="free-hf", model=model, content=content, latency_ms=latency)
        except Exception as e:
            return AIResponse(provider="free-hf", model=model, content="", success=False, error=str(e))


class AIService:
    """Unified AI service with provider failover."""

    def __init__(self):
        self.providers: list[BaseAIProvider] = [
            OpenAIProvider(),
            ClaudeProvider(),
            GeminiProvider(),
            NvidiaProvider(),
            FreeAIProvider(),
        ]

    def chat(self, prompt: str, model: str = "", system: str = "", provider: str = "", **kwargs) -> AIResponse:
        if provider:
            for p in self.providers:
                if p.name == provider and p.is_configured():
                    return p.chat(prompt, model, system, **kwargs)
            return AIResponse(provider=provider, model=model, content="", success=False, error=f"Provider {provider} not configured")

        for p in self.providers:
            if p.is_configured():
                try:
                    result = p.chat(prompt, model, system, **kwargs)
                    if result.success:
                        return result
                    logger.warning("provider_failed", extra={"provider": p.name, "error": result.error})
                except Exception as e:
                    logger.warning("provider_exception", extra={"provider": p.name, "error": str(e)})

        return AIResponse(provider="none", model=model, content="", success=False, error="No AI provider configured or all providers failed")

    def get_status(self) -> list[dict]:
        return [{"name": p.name, "configured": p.is_configured(), "default_model": p.default_model} for p in self.providers]


_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
