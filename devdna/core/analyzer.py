from typing import List, Dict
from collections import defaultdict
from devdna.core.scanner import CodeBlock

class PatternCluster:
    def __init__(self, struct_hash: str):
        self.struct_hash = struct_hash
        self.blocks: List[CodeBlock] = []
        self.confidence = "Low"
        self._source_files: set = set()

    def add(self, code_block: CodeBlock) -> None:
        self.blocks.append(code_block)
        self._source_files.add(str(code_block.filepath))
        self.update_confidence()

    def _update_confidence(self) -> None:
        '''confidence calculation based on occurence:
            High:   >= 10 occurrences across >= 5 unique files (strong for sdk)
            Medium: >= 5 occurrences across >= 3 unique files (common pattern, worth reviewing)
            Low:    Everything else (but still valid for proposal) (might be conincidence, not too much important)
        '''

        count = len(self.blocks)
        unique_files = len(self._source_files)
        if count>=10 and unique_files>=5:
            self.confidence = "High"
        elif count>=5 and unique_files>=3:
            self.confidence = "Medium"
        else:
            self.confidence = "Low"

    @property
    def source_count(self) -> int:
        return len(self.blocks)

    @property
    def unique_file_count(self) -> int:
        return len(self._source_files)

    def __repr__(self) -> str:
        # returns a string that looks liek constructor call with all the attributes
        return (
            f"PatterCluster({self.source_count} sources, {len(self.blocks)} blocks, confidence={self.confidence})"
            f"{self.unique_file_count} unique files"
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
    hash_groups = Dict[str, List[CodeBlock]] = defaultdict(list)

    for block in blocks:
        hash_groups[block.struct_hash].append(block) # blocks grouped by struct_hash

    clusters = []
    for struct_hash, group_blocks in hash_groups.items():
        if len(group_blocks) >= min_cluster_size:
            cluster = PatternCluster(struct_hash)
            for block in group_blocks:
                cluster.add(block)
            clusters.append(cluster) # pattern clusters for above threshold


    #confidence sorting
    clusters.sort(
        key=lambda c: (
            c.confidence != "High",
            c.confidence != "Medium",
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
    high = sum(1 for c in clusters if c.confidence == "High")
    medium = sum(1 for c in clusters if c.confidence == "Medium")
    low = sum(1 for c in clusters if c.confidence == "Low")

    return {
        "total_clusters": len(clusters),
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "total_blocks": sum(c.source_count for c in clusters),
        "total_unique_files": sum(c.unique_file_count for c in clusters),
    }
