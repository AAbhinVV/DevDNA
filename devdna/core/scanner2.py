import ast
import copy
import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import List, Optional, Set

from devdna.config import config


class CodeNormalizer(ast.NodeTransformer):
    """Mutates AST nodes directly in memory without re-parsing raw source text."""

    def visit_Name(self, node: ast.Name) -> ast.Name:
        return ast.Name(id=config.normalization_tokens["name"], ctx=node.ctx)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        return ast.arg(arg=config.normalization_tokens["arg"])

    def visit_keyword(self, node: ast.keyword) -> ast.keyword:
        return ast.keyword(arg=config.normalization_tokens["keyword"])

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Strip docstrings safely from top of function body
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
        node.name = config.normalization_tokens["func_name"]
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
        node.name = config.normalization_tokens["func_name"]
        self.generic_visit(node)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            return ast.Constant(value=config.normalization_tokens["string"])
        elif isinstance(node.value, (int, float)):
            return ast.Constant(value=config.normalization_tokens["number"])
        return node


class CodeBlock:
    """Value object carrying source code, normalized representation, and structural hash."""

    def __init__(
        self,
        source_code: str,
        normalized_code: str,
        filepath: Path,
        func_name: str,
        lineno: int = 0,
    ):
        self.source_code = source_code.strip()
        self.normalized = normalized_code.strip()
        self.filepath = filepath
        self.func_name = func_name
        self.lineno = lineno
        self.struct_hash = hashlib.sha256(
            self.normalized.encode()
        ).hexdigest()[: config.struct_hash_length]

    def __repr__(self) -> str:
        return f"CodeBlock(func_name={self.func_name}, filepath={self.filepath}, lineno={self.lineno})"


class FunctionExtractor(ast.NodeVisitor):
    """Single-pass visitor that extracts and normalizes function definitions with validation."""

    def __init__(self, source_code: str, filepath: Path):
        self.source_code = source_code
        self.filepath = filepath
        self.blocks: List[CodeBlock] = []
        self.normalizer = CodeNormalizer()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._validate_and_extract(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._validate_and_extract(node)
        self.generic_visit(node)

    def _validate_and_extract(self, node: ast.AST) -> None:
        """Validation pipeline for individual function AST nodes."""
        # 1. Structural node type validation
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return

        # 2. Name & line number validation
        if not getattr(node, "name", None) or getattr(node, "lineno", 0) <= 0:
            return

        # 3. Source segment extraction & non-empty check
        try:
            func_source = ast.get_source_segment(self.source_code, node)
        except Exception:
            return

        if not func_source or not func_source.strip():
            return

        # 4. Trivial function body validation (skip empty pass / ... / docstring-only stubs)
        body = node.body
        if not body:
            return
            
        # Check if body consists solely of 'pass' or '...' (Ellipsis)
        if len(body) == 1:
            first_stmt = body[0]
            if isinstance(first_stmt, ast.Pass):
                return
            if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Constant):
                if first_stmt.value.value is Ellipsis or isinstance(first_stmt.value.value, str):
                    # Docstring-only or Ellipsis-only body
                    return

        # 5. AST normalization with resilient exception boundary
        try:
            cloned = copy.deepcopy(node)
            transformed_node = self.normalizer.visit(cloned)
            normalized_code = ast.unparse(transformed_node)
        except Exception:
            # Resiliency: If transformation fails on an unusual AST edge-case, skip this node safely
            return

        # 6. Post-normalization validity check
        if not normalized_code or not normalized_code.strip():
            return

        self.blocks.append(
            CodeBlock(
                source_code=func_source,
                normalized_code=normalized_code,
                filepath=self.filepath,
                func_name=node.name,
                lineno=node.lineno,
            )
        )


def extract_functions(filepath: Path) -> List[CodeBlock]:
    """Reads a file and extracts all normalized function codeblocks using FunctionExtractor."""
    if not isinstance(filepath, Path):
        filepath = Path(filepath)

    try:
        with open(filepath, "r", encoding=config.source_encoding) as f:
            source_code = f.read()
    except (PermissionError, UnicodeDecodeError, OSError):
        return []

    if not source_code or not source_code.strip():
        return []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    # Safety guard: Skip files with absurdly large ASTs (DoS prevention)
    try:
        if sum(1 for _ in ast.walk(tree)) > config.max_ast_nodes:
            return []
    except Exception:
        return []

    extractor = FunctionExtractor(source_code, filepath)
    extractor.visit(tree)
    return extractor.blocks


def scan_directory(
    root: Path = config.scan_root,
    exclude_patterns: Optional[Set[str]] = None,
) -> List[CodeBlock]:
    """Parallel directory scanner utilizing ProcessPoolExecutor with security and validation checks."""
    if not isinstance(root, Path):
        root = Path(root)

    if exclude_patterns is None:
        exclude_patterns = config.exclude_patterns

    py_files: List[Path] = []
    try:
        root_resolved = root.resolve()
    except OSError:
        return []

    for ext in config.source_extensions:
        for py_file in root.rglob(ext):
            if any(part in exclude_patterns for part in py_file.parts):
                continue
            if any(part.startswith(".") and part != "." for part in py_file.parts):
                continue
            try:
                # Symlink protection check
                if not py_file.resolve().is_relative_to(root_resolved):
                    continue
                # File size limit check
                if py_file.stat().st_size > config.max_file_size_bytes:
                    continue
            except OSError:
                continue

            py_files.append(py_file)

    all_blocks: List[CodeBlock] = []

    if py_files:
        max_workers = min(os.cpu_count() or 4, len(py_files))
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            results = executor.map(extract_functions, py_files)
            for blocks in results:
                all_blocks.extend(blocks)

    return all_blocks
