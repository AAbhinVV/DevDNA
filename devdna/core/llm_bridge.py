from typing import List, Dict, Optional, Any
import json
import os
from dataclasses import dataclass
from devdna.config import config



'''
1. Recive pattern cluster, parse to json
2. Build a prompt to teahc llm hwat devdna is and what we want
3. send only normalized code
4. parse LLM json response to PatterProposal 
5. validate output with required field
1 cluster at a time, if 1 fail it doesnt kill the whole process, log and continue
'''

from devdna.core.llm_base import BaseLLMProvider, LLMProviderError

from .scanner import CodeBlock


@dataclass
class PatternCluster:
    struct_hash: str
    code_blocks: List[CodeBlock]
    confidence_score: float
    source_file_count: int
    unique_file_count: int

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

    

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider


    def propose_abstraction(self, cluster: PatternCluster) -> PatternProposal:
        '''send cluster to LLM and get back a PatternProposal'''
        prompt = self._build_prompt(cluster)
        try:
            raw_text = self.provider.complete(prompt)
        except LLMProviderError as e:
            raise LLMBridgeError(str(e)) from e
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

        example_blocks: List[str] = []
        for idx, block in enumerate(examples):
            example_blocks.append(f"### Example {idx} (from {block.filepath.name})\n"
                f"```python\n{block.normalized}\n```")

        examples_str = "\n\n".join(example_blocks)
        prompt = f"""You are the Pattern Abstraction Engine for DevDNA.

DevDNA scans a developer's codebase, finds structurally similar functions, and proposes reusable abstractions to eliminate repetitive boilerplate.

Your task: Analyze the following {len(examples)} structurally similar code examples and design a single, clean, generalized Python function that captures the common pattern.

## Input Examples
These have been normalized (variable names → VAR, strings → STR, numbers → 0) to show pure structure without leaking real data:

{examples_str}

## Cluster Metadata
- Structural Hash: {cluster.struct_hash}
- Total Occurrences: {cluster.source_file_count}
- Unique Files: {cluster.unique_file_count}
- Confidence Score: {cluster.confidence_score:.2f}

## Design Guidelines
1. Identify the true structural pattern — ignore superficial differences.
2. Use descriptive parameter names and Python 3.10+ type hints.
3. Include a clear docstring.
4. If the pattern is trivial (e.g., a one-liner with no real abstraction value), say so in confidence_reasoning.
5. Suggest a module name like "io_utils", "data_helpers", "api_client", etc.

## Output Format
Respond with ONLY a JSON object matching this exact schema. No markdown fences, no extra text:

{{
    "function_name": "snake_case_name",
    "signature": "def snake_case_name(param: type) -> return_type:",
    "implementation": "def snake_case_name(param: type) -> return_type:\\n    \\\"\\\"\\\"Docstring.\\\"\\\"\\\"\\n    ...",
    "suggested_module": "module_name",
    "description": "What this abstraction does in one sentence.",
    "confidence_reasoning": "Why this is a strong or weak abstraction candidate."
}}

Rules:
- Output MUST be valid, parseable JSON.
- `implementation` must be a complete, runnable function as a single string with \\n for newlines.
- Do not wrap the JSON in ```json ... ``` markers.
"""
        return prompt



    #response parsing
    def _parse_response(self, raw_response: str) -> Dict[str, Any]:

        cleaned = raw_response

        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("\n", 1)[0]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            preview  = raw_response[:500].replace("\n", " ")
            raise LLMBridgeError(f"Invalid JSON from Claude. Preview: {preview}...") from e

        required = ("function_name", "signature", "implementation")
        missing = [f for f in required if not data.get(f)]
        if missing:
            raise LLMBridgeError(f"Missing required fields in Claude response: {missing}")

        return data
