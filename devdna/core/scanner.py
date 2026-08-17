import ast
import hashlib
from pathlib import Path
from typing import List, Optional, Set

from devdna.config import config


class CodeBlock:
    def __init__(self, source_code: str, filepath: Path, func_name: str, lineno: int = 0):
        self.source_code = source_code.strip()
        self.filepath = filepath
        self.func_name = func_name
        self.lineno = lineno
        self.normalized = self._normalize()
        self.struct_hash = hashlib.sha256(
            self.normalized.encode()
        ).hexdigest()[:config.struct_hash_length]

    def _normalize(self) -> str:
        tokens = config.normalization_tokens
        try:
            tree = ast.parse(self.source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    node.id = tokens["name"]
                elif isinstance(node, ast.arg):
                    node.arg = tokens["arg"]
                elif isinstance(node, ast.keyword):
                    node.keyword = tokens["keyword"]
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    node.name = tokens["func_name"]
                elif isinstance(node, ast.Constant):
                    if isinstance(node.value, str):
                        node.value = tokens["string"]
                    elif isinstance(node.value, (int, float)):
                        node.value = tokens["number"]
            return ast.unparse(tree)
        except (SyntaxError, ValueError):
            return ""

    def __repr__(self) -> str:
        return f"CodeBlock(func_name={self.func_name}, filepath={self.filepath}, lineno={self.lineno})"


def scan_directory(
    root: Path = config.scan_root,
    exclude_patterns: Optional[Set[str]] = None
) -> List[CodeBlock]:
    if exclude_patterns is None:
        exclude_patterns = config.exclude_patterns

    all_blocks: List[CodeBlock] = []
    for ext in config.source_extensions:
        for py_file in root.rglob(ext):
            # skip excluded directories
            if any(part in exclude_patterns for part in py_file.parts):
                continue

            # skip hidden files
            if any(part.startswith('.') and part != '.' for part in py_file.parts):
                continue

            # skip oversized files
            try:
                if py_file.stat().st_size > config.max_file_size_bytes:
                    continue
            except OSError:
                continue

            blocks = extract_functions(py_file)
            all_blocks.extend(blocks)

    return all_blocks


def extract_functions(filepath: Path) -> List[CodeBlock]:
    try:
        with open(filepath, 'r', encoding=config.source_encoding) as file:
            source_code = file.read()
    except (PermissionError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    # Safety guard: skip files with absurdly large ASTs
    if sum(1 for _ in ast.walk(tree)) > config.max_ast_nodes:
        return []

    functions: List[CodeBlock] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_source = ast.get_source_segment(source_code, node)
            if func_source:
                block = CodeBlock(func_source, filepath, node.name, node.lineno)
                if block.normalized:
                    functions.append(block)

    return functions