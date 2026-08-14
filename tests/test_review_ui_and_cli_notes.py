"""
Testing Notes for Review UI & CLI

These components are interactive and best tested manually or with
integration-style scripts. Unit tests are limited due to Rich/Typer
terminal dependencies.

Run: python tests/test_review_ui_and_cli_notes.py
"""

from pathlib import Path

from devdna.core.memory import MemoryStore


def seed_test_data(store: MemoryStore):
    """Helper: Insert fake proposals for manual review testing."""
    proposals = [
        {
            "function_name": "retry_request",
            "signature": "def retry_request(url: str, max_retries: int = 3) -> Response:",
            "implementation": 'def retry_request(url: str, max_retries: int = 3) -> Response:\n    """Retry HTTP request with exponential backoff."""\n    for attempt in range(max_retries):\n        try:\n            return requests.get(url)\n        except RequestException:\n            if attempt == max_retries - 1:\n                raise\n            time.sleep(2 ** attempt)',
            "source_hash": "hash_retry_001",
            "example_count": 8,
            "suggested_module": "api_client",
            "description": "Retries failed HTTP requests with backoff.",
            "confidence_reasoning": "Found in 8 files across 4 projects. Strong structural match.",
        },
        {
            "function_name": "clean_dataframe",
            "signature": "def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:",
            "implementation": 'def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:\n    """Drop nulls and reset index."""\n    return df.dropna().reset_index(drop=True)',
            "source_hash": "hash_clean_002",
            "example_count": 5,
            "suggested_module": "data_utils",
            "description": "Standard DataFrame cleaning pipeline.",
            "confidence_reasoning": "Common pattern, 5 occurrences across 3 files.",
        },
        {
            "function_name": "setup_logger",
            "signature": "def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:",
            "implementation": 'def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:\n    """Configure structured logger."""\n    logger = logging.getLogger(name)\n    logger.setLevel(level)\n    return logger',
            "source_hash": "hash_log_003",
            "example_count": 12,
            "suggested_module": "logging_utils",
            "description": "Configure a logger with handlers.",
            "confidence_reasoning": "Very common, 12 occurrences across 6 files. High confidence.",
        },
    ]
    saved = 0
    for p in proposals:
        pid = store.save_proposal(p)
        if pid:
            saved += 1
    print(f"Seeded {saved}/{len(proposals)} test proposals.")
    return saved


def print_manual_workflow():
    """Print the manual testing checklist."""
    print("=" * 60)
    print("MANUAL TEST WORKFLOW FOR REVIEW UI & CLI")
    print("=" * 60)
    print()
    print("1. Seed test data:")
    print("   python tests/test_review_ui_and_cli_notes.py")
    print()
    print("2. Test Review UI:")
    print("   devdna review")
    print("   → Try: [A]ccept first, [R]eject second, [S]kip third")
    print("   → Verify summary shows correct counts")
    print("   → Verify gist table shows remaining patterns")
    print()
    print("3. Test Status:")
    print("   devdna status")
    print("   → Verify pending/accepted/rejected counts match your decisions")
    print()
    print("4. Test Generate:")
    print("   devdna generate --name test_sdk --output ./test_sdk")
    print("   → Verify directory structure")
    print("   → pip install -e ./test_sdk")
    print("   → python -c \"from test_sdk import retry_request\"")
    print()
    print("5. Test CLI edge cases:")
    print("   devdna sync /nonexistent/path     → Should fail gracefully")
    print("   devdna generate                   → Should warn if no accepted")
    print("   devdna review (with no pending)    → Should say 'No pending'")
    print()
    print("6. Test re-sync deduplication:")
    print("   devdna sync <same-project>")
    print("   → Should report 0 new proposals (all hashes exist)")
    print()


if __name__ == "__main__":
    print_manual_workflow()

    # Actually seed the data
    store = MemoryStore()
    count = seed_test_data(store)
    print()
    if count > 0:
        print("Test data seeded. Run the commands above to verify.")
    else:
        print("No new proposals seeded (duplicates may already exist).")