from typing import Optional
from devdna.config import config
from devdna.core.llm_base import BaseLLMProvider, LLMProviderError

try:
    from anthropic import Anthropic, APIError, APITimeoutError
except ImportError:
    Anthropic = None

class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        if Anthropic is None:
            raise LLMProviderError("Anthropic package not installed. Run: pip install anthropic>=0.30.0")
        
        self.api_key = api_key or config.anthropic_api_key
        if not self.api_key:
            raise LLMProviderError("Anthropic API key not provided. Set the 'ANTHROPIC_API_KEY' environment variable.")

        self.model = model or config.llm_model
        self.client = Anthropic(api_key=self.api_key)

    def complete(self, prompt: str) -> str:
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=config.llm_max_tokens,
                temperature=config.llm_temperature,
                messages=[{"role": "user", "content": prompt}]
            )
        except APITimeoutError as e:
            raise LLMProviderError(f"Claude API timeout: {e}")
        except APIError as e:
            raise LLMProviderError(f"API error: {e}")
        except Exception as e:
            raise LLMProviderError(f"Unexpected Claude error: {e}")

        if not message.content or not message.content[0].text:
            raise LLMProviderError("Claude returned empty content.")

        return message.content[0].text.strip()
