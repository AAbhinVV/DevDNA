from typing import List, Dict, Optional, Any
import json
import os
from dataclasses import dataclass



'''
1. Recive pattern cluster, parse to json
2. Build a prompt to teahc llm hwat devdna is and what we want
3. send only normalized code
4. parse LLM json response to PatterProposal 
5. validate output with required field
1 cluster at a time, if 1 fail it doesnt kill the whole process, log and continue
'''

try:
    from anthropic import Anthropic, APIError, APITimeoutError
except ImportError:
    Anthropic = None #defer erro until instantiation

from .scanner import CodeBlock


@dataclass
class PatternCluster:
    struct_hash: str
    code_blocks: List[CodeBlock]
    confidence_score: float
    source_file_count: int
    unqiue_file_count: int

    def top_examples(self, n: int = 3) -> List[CodeBlock]:
        return self.code_blocks[:n]


@dataclass
class PatternProposal:
    function_name: str
    signature: str
    implementation: str
    suggested_module: str
    description: str
    confidence_reasoning: str
    source_hash: str
    example_count: int


class LLMBridgeError(Exception):
    pass

class LLMBridge: 
    '''one cluster per api call, temp 0.2, json-over-text, normalized code in prompts'''

    DEFAULT_MODEL = "claude-sonnet-4-25250514"
    MAX_TOKENS = 4096

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        if Anthropic is None:
            raise LLMBridgeError("Anthropic package not installed. Run: pip install anthropic>=0.30.0")
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise LLMBridgeError("Anthropic API key not provided. Set the 'ANTHROPIC_API_KEY' environment variable or pass it to the constructor.")

        self.model = model or self.DEFAULT_MODEL
        self.client = Anthropic(api_key=self.api_key)


    def propose_abstraction(self, cluster: PatternCluster) -> PatternProposal:
        '''send cluster to LLM and get back a PatternProposal'''
        prompt = self._build_prompt(cluster)
        raw_text = self._call_claude(prompt)
        parsed = self._parse_response(raw_text)

        return PatternProposal(
            function_name=parsed["function_name"],
            signature=parsed["signature"],
            implementation=parsed["implementation"],
            suggested_module=parsed.get("suggested_module", "utils"),
            description=parsed.get("description", ""),
            confidence_reasoning=parsed.get("confidence_reasoning", ""),
            source_hash=cluster.struct_hash,
            example_count=len(cluster.code_blocks),
        )


    def propose_batch(self, clusters: List[PatternCluster]) -> List[PatternProposal]:
        """
        Process many clusters, skipping failures.
        Returns only successful proposals. The caller (cli.py) decides
        whether to log warnings or abort.
        """
        proposals: List[PatternProposal] = []
        for cluster in clusters:
            try:
                proposal = self.propose_abstraction(cluster)
                proposals.append(proposal)
            except LLMBridgeError as e:
                print(f"[LLMBridge] Skipped cluster {cluster.struct_hash[:8]}: {e}")
                continue
        return proposals

    def _build_prompt(self, cluster: PatternCluster) -> str:
        examples = cluster.top_examples(3)

        example_blocks = (
