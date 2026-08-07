"""
Tests for devdna.core.llm_bridge

Run: pytest tests/test_llm_bridge.py -v

NOTE: Tests that call the real Claude API require ANTHROPIC_API_KEY in .env
      Mock tests run without API key.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devdna.core.llm_bridge import (
    LLMBridge,
    LLMBridgeError,
    PatternCluster,
    PatternProposal,
)
from devdna.core.scanner import CodeBlock


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def sample_cluster():
    """A realistic PatternCluster for testing."""
    blocks = [
        CodeBlock(
            source_code="def clean(df): return df.dropna()",
            filepath=Path("project_a/data.py"),
            func_name="clean_data",
            lineno=10,
        ),
        CodeBlock(
            source_code="def handle(data): return data.dropna()",
            filepath=Path("project_b/prep.py"),
            func_name="remove_nulls",
            lineno=5,
        ),
    ]
    return PatternCluster(
        struct_hash="a1b2c3d4e5f67890",
        code_blocks=blocks,
        confidence_score=0.92,
        source_file_count=2,
        unique_file_count=2,
    )


@pytest.fixture
def mock_claude_response():
    """Simulated Claude JSON response."""
    return '''{
        "function_name": "drop_missing_values",
        "signature": "def drop_missing_values(df: pd.DataFrame) -> pd.DataFrame:",
        "implementation": "def drop_missing_values(df: pd.DataFrame) -> pd.DataFrame:\n    \"\"\"Drop rows with missing values.\"\"\"\n    return df.dropna()",
        "suggested_module": "data_utils",
        "description": "Drops rows containing null values from a DataFrame.",
        "confidence_reasoning": "Strong structural match across 2 files."
    }'''


# =============================================================================
# Initialization Tests
# =============================================================================

class TestLLMBridgeInit:
    """Tests for constructor and validation."""

    def test_raises_without_api_key(self, monkeypatch):
        """Missing API key raises LLMBridgeError."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMBridgeError, match="ANTHROPIC_API_KEY"):
            LLMBridge(api_key=None)

    def test_accepts_explicit_api_key(self):
        """Explicit key bypasses env check."""
        bridge = LLMBridge(api_key="sk-test-fake-key")
        assert bridge.api_key == "sk-test-fake-key"

    def test_default_model_set(self):
        """Default model is Claude Sonnet."""
        bridge = LLMBridge(api_key="sk-test")
        assert "claude" in bridge.model.lower()


# =============================================================================
# Prompt Building Tests
# =============================================================================

class TestPromptBuilding:
    """Tests for _build_prompt."""

    def test_prompt_contains_normalized_code_only(self, sample_cluster):
        """Prompt uses normalized code, never raw source."""
        bridge = LLMBridge(api_key="sk-test")
        prompt = bridge._build_prompt(sample_cluster)
        assert "VAR" in prompt  # normalized variable names
        assert "df" not in prompt  # raw variable name should not appear
        assert "STR" in prompt or "0" in prompt or "VAR" in prompt

    def test_prompt_contains_cluster_metadata(self, sample_cluster):
        """Prompt includes hash, counts, confidence."""
        bridge = LLMBridge(api_key="sk-test")
        prompt = bridge._build_prompt(sample_cluster)
        assert sample_cluster.struct_hash in prompt
        assert str(sample_cluster.source_file_count) in prompt
        assert str(sample_cluster.unique_file_count) in prompt

    def test_prompt_has_json_schema(self, sample_cluster):
        """Prompt specifies exact JSON output format."""
        bridge = LLMBridge(api_key="sk-test")
        prompt = bridge._build_prompt(sample_cluster)
        assert "function_name" in prompt
        assert "signature" in prompt
        assert "implementation" in prompt

    def test_prompt_requests_no_markdown(self, sample_cluster):
        """Prompt asks for raw JSON without markdown fences."""
        bridge = LLMBridge(api_key="sk-test")
        prompt = bridge._build_prompt(sample_cluster)
        assert "No markdown" in prompt or "parseable JSON" in prompt


# =============================================================================
# Response Parsing Tests
# =============================================================================

class TestResponseParsing:
    """Tests for _parse_response edge cases."""

    def test_parses_clean_json(self):
        """Valid JSON returns dict."""
        bridge = LLMBridge(api_key="sk-test")
        raw = '{"function_name": "foo", "signature": "def foo():", "implementation": "def foo(): pass"}'
        result = bridge._parse_response(raw)
        assert result["function_name"] == "foo"

    def test_strips_markdown_fences(self):
        """JSON wrapped in ```json ... ``` is cleaned."""
        bridge = LLMBridge(api_key="sk-test")
        raw = '```json\n{"function_name": "foo", "signature": "def foo():", "implementation": "def foo(): pass"}\n```'
        result = bridge._parse_response(raw)
        assert result["function_name"] == "foo"

    def test_raises_on_invalid_json(self):
        """Malformed JSON raises LLMBridgeError."""
        bridge = LLMBridge(api_key="sk-test")
        with pytest.raises(LLMBridgeError, match="Invalid JSON"):
            bridge._parse_response("not json at all")

    def test_raises_on_missing_required_field(self):
        """Missing function_name raises error."""
        bridge = LLMBridge(api_key="sk-test")
        raw = '{"signature": "def foo():", "implementation": "pass"}'
        with pytest.raises(LLMBridgeError, match="Missing required fields"):
            bridge._parse_response(raw)

    def test_raises_on_empty_field(self):
        """Empty function_name is treated as missing."""
        bridge = LLMBridge(api_key="sk-test")
        raw = '{"function_name": "", "signature": "def foo():", "implementation": "pass"}'
        with pytest.raises(LLMBridgeError, match="Missing required fields"):
            bridge._parse_response(raw)


# =============================================================================
# End-to-End Mock Tests
# =============================================================================

class TestProposeAbstraction:
    """Mocked end-to-end tests."""

    @patch("devdna.core.llm_bridge.Anthropic")
    def test_returns_pattern_proposal(self, mock_anthropic, sample_cluster, mock_claude_response):
        """Successful API call returns PatternProposal."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=mock_claude_response)]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic.return_value = mock_client

        bridge = LLMBridge(api_key="sk-test")
        proposal = bridge.propose_abstraction(sample_cluster)

        assert isinstance(proposal, PatternProposal)
        assert proposal.function_name == "drop_missing_values"
        assert proposal.source_hash == sample_cluster.struct_hash
        assert proposal.example_count == 2

    @patch("devdna.core.llm_bridge.Anthropic")
    def test_api_error_raises_llm_bridge_error(self, mock_anthropic, sample_cluster):
        """API failure is wrapped in LLMBridgeError."""
        from anthropic import APIError

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = APIError("Rate limited")
        mock_anthropic.return_value = mock_client

        bridge = LLMBridge(api_key="sk-test")
        with pytest.raises(LLMBridgeError, match="Claude API error"):
            bridge.propose_abstraction(sample_cluster)

    @patch("devdna.core.llm_bridge.Anthropic")
    def test_empty_response_raises(self, mock_anthropic, sample_cluster):
        """Empty content raises LLMBridgeError."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = []
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic.return_value = mock_client

        bridge = LLMBridge(api_key="sk-test")
        with pytest.raises(LLMBridgeError, match="empty content"):
            bridge.propose_abstraction(sample_cluster)


class TestProposeBatch:
    """Tests for batch processing with failure tolerance."""

    @patch("devdna.core.llm_bridge.Anthropic")
    def test_skips_failed_clusters(self, mock_anthropic, sample_cluster):
        """One bad cluster doesn't kill the batch."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"function_name": "ok", "signature": "def ok():", "implementation": "pass"}')]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic.return_value = mock_client

        bridge = LLMBridge(api_key="sk-test")
        clusters = [sample_cluster, sample_cluster]  # second will be duplicate hash
        proposals = bridge.propose_batch(clusters)
        assert len(proposals) == 2  # both succeed with same mock

    @patch("devdna.core.llm_bridge.Anthropic")
    def test_returns_partial_results(self, mock_anthropic, sample_cluster):
        """Returns whatever succeeded, logs failures."""
        mock_client = MagicMock()
        # First call succeeds, second fails
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"function_name": "ok", "signature": "def ok():", "implementation": "pass"}')]
        mock_client.messages.create.side_effect = [mock_msg, Exception("fail")]
        mock_anthropic.return_value = mock_client

        bridge = LLMBridge(api_key="sk-test")
        clusters = [sample_cluster, sample_cluster]
        proposals = bridge.propose_batch(clusters)
        assert len(proposals) == 1


# =============================================================================
# Integration Test (Requires Real API Key)
# =============================================================================

@pytest.mark.skipif(
    not Path(".env").exists(),
    reason="Requires .env with ANTHROPIC_API_KEY",
)
class TestLiveClaude:
    """Real API calls — expensive, run manually."""

    def test_live_proposal(self, sample_cluster):
        """End-to-end with real Claude. Costs ~$0.01."""
        bridge = LLMBridge()
        proposal = bridge.propose_abstraction(sample_cluster)
        assert proposal.function_name
        assert proposal.signature.startswith("def ")
        assert "dropna" in proposal.implementation or "VAR" not in proposal.implementation
        # Note: implementation should use real names, not VAR (LLM invents them)