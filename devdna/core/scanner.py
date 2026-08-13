# read python file
# parse to abstract syntax tree
# extract function definitions
# normalization

import ast
import hashlib
from pathlib import Path
from typing import List, Optional, Set


DEFAULT_EXCLUDE_PATTERNS = {
    '.venv', 'venv', 'env', 'virtualenv',
    '__pycache__', '.pytest_cache', '.mypy_cache', '.tox', '.egg-info',
    '.git', '.hg', '.svn',
    'node_modules', 'vendor', '.bundle',
    '.idea', '.vscode', '.vim',
    'build', 'dist', 'target', 'out', 'site-packages',
    'docs/_build', '_build', 'htmlcov', '.coverage',
    '.env', '.env.local', '.env.dev', '.env.staging', '.env.production',
    '.envrc', '.flaskenv', '.djangoenv',
    'secrets', 'credentials', 'keys', 'private', '.ssh', '.gnupg',
    'fixtures', 'testdata', 'test_data', 'sample_data',
    'tmp', 'temp', '.tmp', '.temp', 'cache', '.cache',
    '.DS_Store', 'Thumbs.db', 'desktop.ini',
    'logs', 'log',
    '.github', '.gitlab-ci', '.circleci',
}


class CodeBlock:
    def __init__(self, source_code: str, filepath: Path, func_name: str, lineno: int = 0):
        self.source_code = source_code.strip()
        self.filepath = filepath
        self.func_name = func_name
        self.lineno = lineno
        self.normalized = self._normalize()
        self.struct_hash = hashlib.sha256(self.normalized.encode()).hexdigest()[:16]

    def _normalize(self) -> str:
        try:
            tree = ast.parse(self.source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    node.id = 'VAR'
                elif isinstance(node, ast.arg):
                    node.arg = 'ARG'
                elif isinstance(node, ast.keyword):
                    node.keyword = 'VAR'
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    node.name = 'FUNC'
                elif isinstance(node, ast.Constant):
                    if isinstance(node.value, str):
                        node.value = "STR"
                    elif isinstance(node.value, (int, float)):
                        node.value = 0
            return ast.unparse(tree)
        except (SyntaxError, ValueError):
            return ""

    def __repr__(self) -> str:
        return f"CodeBlock(func_name={self.func_name}, filepath={self.filepath}, lineno={self.lineno})"


def scan_directory(
    root: Path = Path("."),
    exclude_patterns: Optional[Set[str]] = None
) -> List[CodeBlock]:
    if exclude_patterns is None:
        exclude_patterns = DEFAULT_EXCLUDE_PATTERNS

    all_blocks: List[CodeBlock] = []
    for py_file in root.rglob("*.py"):
        # skip excluded directories
        if any(part in exclude_patterns for part in py_file.parts):
            continue

        # skip hidden files
        if any(part.startswith('.') and part != '.' for part in py_file.parts):
            continue

        blocks = extract_functions(py_file)
        all_blocks.extend(blocks)

    return all_blocks


def extract_functions(filepath: Path) -> List[CodeBlock]:
    # python file parsing and extracting function definitions
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            source_code = file.read()
    except (PermissionError, UnicodeDecodeError):
        return []

    # parse
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    functions: List[CodeBlock] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_source = ast.get_source_segment(source_code, node)
            if func_source:
                block = CodeBlock(func_source, filepath, node.name, node.lineno)
                if block.normalized:
                    functions.append(block)

    return functions