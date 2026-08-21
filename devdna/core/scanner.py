import ast
import copy
import hashlib
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Generator, List, Optional, Set

from devdna.config import config

logger = logging.getLogger(__name__)


class _AstTooLargeError(Exception):
    """Raised internally when a file's AST exceeds config.max_ast_nodes."""


class CodeNormalizer(ast.NodeTransformer):
    """Normalizes AST nodes IN PLACE on an owned deepcopy of the function node."""

    def _strip_docstring(self, node) -> None:
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = config.normalization_tokens["name"]
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = config.normalization_tokens["arg"]
        return node

    def visit_keyword(self, node: ast.keyword) -> ast.keyword:
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self._strip_docstring(node)
        node.name = config.normalization_tokens["func_name"]
        node.decorator_list = []
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self._strip_docstring(node)
        node.name = config.normalization_tokens["func_name"]
        node.decorator_list = []
        self.generic_visit(node)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            node.value = config.normalization_tokens["string"]
        elif isinstance(node.value, (int, float)):
            node.value = config.normalization_tokens["number"]
        return node


class CodeBlock:
    """Value object carrying source code, normalized representation, and structural hash."""

    __slots__ = ("source_code", "normalized", "filepath", "func_name", "lineno", "struct_hash")

    def __init__(
        self,
        source_code: str,
        filepath: object = None,
        func_name: str = "",
        lineno: int = 0,
        normalized_code: Optional[str] = None,
    ):
        self.source_code = source_code.strip()

        # Handle positional overload: CodeBlock(source, normalized_code, filepath, func_name, lineno)
        if isinstance(filepath, str) and normalized_code is None and isinstance(func_name, Path):
            normalized_code = filepath
            filepath = func_name
            func_name = str(lineno)
            lineno = 0
        elif isinstance(filepath, str) and normalized_code is None and not func_name:
            normalized_code = filepath
            filepath = Path(".")
            func_name = ""

        if not isinstance(filepath, Path):
            filepath = Path(str(filepath)) if filepath else Path(".")

        self.filepath = filepath
        self.func_name = str(func_name) if func_name else ""
        self.lineno = int(lineno) if lineno else 0

        if normalized_code is None:
            try:
                tree = ast.parse(self.source_code)
                norm_node = CodeNormalizer().visit(tree)
                self.normalized = ast.unparse(norm_node).strip()
            except Exception:
                self.normalized = ""
        else:
            self.normalized = normalized_code.strip()

        self.struct_hash = hashlib.sha256(
            self.normalized.encode()
        ).hexdigest()[: config.struct_hash_length]

    def __repr__(self) -> str:
        return f"CodeBlock(func_name={self.func_name}, filepath={self.filepath}, lineno={self.lineno})"


class FunctionExtractor(ast.NodeVisitor):
    """Single-pass visitor that extracts and normalizes function definitions."""

    def __init__(self, source_code: str, filepath: Path):
        self.source_code = source_code
        self.filepath = filepath
        self.blocks: List[CodeBlock] = []
        self.normalizer = CodeNormalizer()
        self._nodes_seen = 0
        self.skipped_functions = 0

    def visit(self, node: ast.AST) -> None:
        self._nodes_seen += 1
        if self._nodes_seen > config.max_ast_nodes:
            raise _AstTooLargeError
        super().visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._validate_and_extract(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._validate_and_extract(node)
        self.generic_visit(node)

    @staticmethod
    def _contains_nested_def(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if child is not node and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
        return False

    def _normalize_node(self, node: ast.AST) -> Optional[str]:
        try:
            if self._contains_nested_def(node):
                working = copy.deepcopy(node)
            else:
                working = node
            transformed = self.normalizer.visit(working)
            normalized_code = ast.unparse(transformed)
        except Exception:
            logger.debug("Normalization failed for %s:%s", self.filepath, getattr(node, "lineno", "?"), exc_info=True)
            return None
        if not normalized_code or not normalized_code.strip():
            return None
        return normalized_code

    def _validate_and_extract(self, node: ast.AST) -> None:
        original_name = getattr(node, "name", None)
        if not original_name or getattr(node, "lineno", 0) <= 0:
            self.skipped_functions += 1
            return

        try:
            func_source = ast.get_source_segment(self.source_code, node)
        except Exception:
            self.skipped_functions += 1
            return

        if not func_source or not func_source.strip():
            self.skipped_functions += 1
            return

        # Trivial body validation: skip pass / ... / docstring-only stubs.
        # All trivial stubs normalize to an identical hash and would form a
        # single meaningless cluster in the analyzer.
        if config.skip_trivial_stubs:
            body = node.body
            if body and len(body) == 1:
                first_stmt = body[0]
                if isinstance(first_stmt, ast.Pass):
                    logger.debug("Skipping pass-only stub %s:%s", self.filepath, node.lineno)
                    self.skipped_functions += 1
                    return
                if (
                    isinstance(first_stmt, ast.Expr)
                    and isinstance(first_stmt.value, ast.Constant)
                    and (first_stmt.value.value is Ellipsis or isinstance(first_stmt.value.value, str))
                ):
                    logger.debug("Skipping docstring/ellipsis-only stub %s:%s", self.filepath, node.lineno)
                    self.skipped_functions += 1
                    return

        normalized_code = self._normalize_node(node)
        if normalized_code is None:
            self.skipped_functions += 1
            return

        self.blocks.append(
            CodeBlock(
                source_code=func_source,
                normalized_code=normalized_code,
                filepath=self.filepath,
                func_name=original_name,
                lineno=node.lineno,
            )
        )


def extract_functions(filepath: Path) -> List[CodeBlock]:
    """Reads a file and extracts all normalized function codeblocks."""
    if not isinstance(filepath, Path):
        filepath = Path(filepath)

    try:
        with open(filepath, "r", encoding=config.source_encoding) as f:
            source_code = f.read()
    except (PermissionError, UnicodeDecodeError, OSError) as exc:
        logger.debug("Skipped unreadable file %s: %s", filepath, exc)
        return []

    if not source_code or not source_code.strip():
        return []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        logger.debug("Skipped file with syntax errors: %s", filepath)
        return []
    except (ValueError, RecursionError) as exc:
        logger.debug("Failed to parse %s: %s", filepath, exc)
        return []

    extractor = FunctionExtractor(source_code, filepath)
    try:
        extractor.visit(tree)
    except _AstTooLargeError:
        logger.debug("Skipped oversized AST (%d+ nodes): %s", config.max_ast_nodes, filepath)
        return []
    except RecursionError:
        logger.warning("Recursion limit hit while visiting %s", filepath)
        return []

    return extractor.blocks


def discover_python_files(
    root: Path,
    exclude_patterns: Set[str],
) -> List[Path]:
    try:
        root_resolved = root.resolve()
    except OSError:
        return []

    suffixes = {
        pat[1:] if pat.startswith("*") else pat
        for pat in config.source_extensions
    }
    py_files: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in exclude_patterns and not d.startswith(".")
        )

        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            if Path(fname).suffix not in suffixes:
                continue

            fpath = Path(dirpath) / fname
            try:
                if fpath.is_symlink():
                    if not fpath.resolve().is_relative_to(root_resolved):
                        continue
                if fpath.stat().st_size > config.max_file_size_bytes:
                    logger.debug("Skipped oversized file: %s", fpath)
                    continue
            except OSError:
                continue

            py_files.append(fpath)

    return py_files


def iter_scan_directory(
    root: Path = config.scan_root,
    exclude_patterns: Optional[Set[str]] = None,
) -> Generator[CodeBlock, None, None]:
    if not isinstance(root, Path):
        root = Path(root)

    if exclude_patterns is None:
        exclude_patterns = config.exclude_patterns

    py_files = discover_python_files(root, exclude_patterns)
    logger.info("Discovered %d python files under %s", len(py_files), root)

    if not py_files:
        return

    if len(py_files) < config.parallel_min_files:
        logger.debug("File count below threshold (%d); scanning sequentially", len(py_files))
        for f in py_files:
            yield from extract_functions(f)
        return

    max_workers = min(config.scan_max_workers or os.cpu_count() or 4, len(py_files))
    logger.debug("Scanning with %d worker processes", max_workers)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(extract_functions, f): f for f in py_files}
        for future in as_completed(futures):
            src = futures[future]
            try:
                blocks = future.result()
            except Exception:
                logger.warning("Worker failed on %s", src, exc_info=True)
                continue
            yield from blocks


def scan_directory(
    root: Path = config.scan_root,
    exclude_patterns: Optional[Set[str]] = None,
) -> List[CodeBlock]:
    return list(iter_scan_directory(root, exclude_patterns))