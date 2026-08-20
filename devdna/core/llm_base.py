from abc import ABC, abstractmethod

class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""
    pass

class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers in DevDNA."""
    
    @abstractmethod
    def __init__(self, api_key: str = None, model: str = None):
        """Initialize the LLM provider with API key and model."""
        pass

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """
        Send a prompt to the LLM and return the raw text response.
        
        Args:
            prompt: The instruction prompt containing code patterns.
            
        Returns:
            The raw string response from the LLM.
            
        Raises:
            LLMProviderError: If the API call fails or times out.
        """
        pass
