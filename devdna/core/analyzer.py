from __future__ import annotations

from typing import List, Dict, Optional, Set
from pathlib import Path
from collections import defaultdict
from devdna.core.scanner import CodeBlock

class PatternCluster:

    HIGH_THRESHOLD  =(10,5)
    MEDIUM_THRESHOLD=(5,3)

    def __init__(self, struct_hash: str):
        self.struct_hash = struct_hash
        self.blocks: List[CodeBlock] = []
        self._source_files: Set[Path] = set()
        self._confidence_label = "Low"
        self._confidence_score = 0.0

    def add(self, code_block: CodeBlock) -> None:
        self.blocks.append(code_block)
        self._source_files.add(code_block.filepath)
        self._recalculate_confidence()


    def _recalculate_confidence(self) -> None:
        '''confidence calculation based on occurence:
            High:   >= 10 occurrences across >= 5 unique files (strong for sdk)
            Medium: >= 5 occurrences across >= 3 unique files (common pattern, worth reviewing)
            Low:    Everything else (but still valid for proposal) (might be conincidence, not too much important)
        '''

        count = len(self.blocks)
        unique_files = len(self._source_files)
        if count>=self.HIGH_THRESHOLD[0] and unique_files>=self.HIGH_THRESHOLD[1]:
            self._confidence_label = "High"
            self._confidence_score = 0.9
        elif count>=self.MEDIUM_THRESHOLD[0] and unique_files>=self.MEDIUM_THRESHOLD[1]:
            self._confidence_label = "Medium"
            self._confidence_score = 0.6
        else:
            self._confidence_label = "Low"
            self._confidence_score = 0.3

    @property
    def confidence_score(self) -> float:
        return self._confidence_score

    @property
    def confidence_label(self) -> str:
        return self._confidence_label

    @property
    def source_count(self) -> int:
        return len(self.blocks)

    @property
    def unique_file_count(self) -> int:
        return len(self._source_files)

    def top_examples(self, n: int = 3) -> List[CodeBlock]:
        '''return top n examples of code blocks in this cluster'''
        return self.blocks[:n]

    def __repr__(self) -> str:
        # returns a string that looks liek constructor call with all the attributes
        return (
            f"PatternCluster("
            f"hash={self.struct_hash[:8]}..., "
            f"blocks={len(self.blocks)}, "
            f"files={self.unique_file_count}, "
            f"confidence={self._confidence_label}"
            f")"
        )

    def __len__(self) -> int:
        return len(self.blocks)

def cluster_by_structure(
        blocks: List[CodeBlock],
        min_cluster_size: int = 2
    ) -> List[ PatternCluster]:
    """
    Group CodeBlocks by structural similarity (exact hash match).
    
    This is the core clustering algorithm. It uses a dictionary to group
    blocks by their struct_hash, then filters out small clusters and
    sorts by confidence.
    
    Args:
        blocks: List of CodeBlock objects from scanner
        min_cluster_size: Minimum blocks to form a cluster (default: 2)
                         Set to 1 to include all patterns (noisy).
                         Set to 3+ for stricter filtering.
    
    Returns:
        List of PatternCluster objects, sorted by confidence then size.
        Empty list if no patterns found.
    
    Algorithm Complexity:
        Time: O(n) where n = number of blocks
        Space: O(n) for the hash_groups dictionary
    
    Example:
        >>> blocks = scan_directory(Path("~/project"))
        >>> clusters = cluster_by_structure(blocks, min_cluster_size=2)
        >>> for c in clusters:
        ...     print(f"{c.confidence}: {c.representative.func_name}")
        High: preprocess
        Medium: load_data
        Low: helper_function
    """
    hash_groups: Dict[str, List[CodeBlock]] = defaultdict(list)

    for block in blocks:
        if block.struct_hash:
            hash_groups[block.struct_hash].append(block) # blocks grouped by struct_hash

    clusters: List[PatternCluster] = []
    for struct_hash, group_blocks in hash_groups.items():
        if len(group_blocks) >= min_cluster_size:
            cluster = PatternCluster(struct_hash)
            for block in group_blocks:
                cluster.add(block)
            clusters.append(cluster) # pattern clusters for above threshold


    #confidence sorting
    confidence_order = {"High": 0, "Medium": 1, "Low": 2}
    clusters.sort(
        key=lambda c: (
            confidence_order[c.confidence_label],
            -c.source_count #descending sort
        )
    )

    return clusters



def analyze_patterns(
        blocks: List[CodeBlock],
        min_cluster_size: int = 2,
        max_cluster: int = 50
    ) -> List[PatternCluster]:
    """
    High-level analysis function: cluster, filter, and rank patterns.
    
    This is the main entry point for the analyzer. It wraps clustering
    with additional filtering for production use.
    
    Args:
        blocks: List of CodeBlock objects from scanner
        min_cluster_size: Minimum blocks per cluster (default: 2)
        max_clusters: Maximum clusters to return (default: 50)
                       Prevents overwhelming the user/LLM with too many proposals.
    
    Returns:
        Top N PatternCluster objects, sorted by importance.
    
    Example:
        >>> blocks = scan_directory(Path("~/project"))
        >>> top_patterns = analyze_patterns(blocks, min_cluster_size=3, max_clusters=10)
        >>> print(f"Found {len(top_patterns)} significant patterns")
    """

    clusters = cluster_by_structure(blocks, min_cluster_size)

    #top N clusters
    #priority high confidence fist then largest
    return clusters[:max_cluster]


def get_cluster_stats(clusters: List[PatternCluster]) -> dict:
    '''stats about found patterns for reporting'''
    high = sum(1 for c in clusters if c.confidence_label == "High")
    medium = sum(1 for c in clusters if c.confidence_label == "Medium")
    low = sum(1 for c in clusters if c.confidence_label == "Low")

    return {
        "total_clusters": len(clusters),
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "total_blocks": sum(c.source_count for c in clusters),
        "total_unique_files": sum(c.unique_file_count for c in clusters),
    }
