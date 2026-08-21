"""One-off verification: are all v1/v2 hash mismatches explained by decorators?"""
import difflib
import tempfile
from pathlib import Path

from devdna.core.scanner import CodeBlock as V1
from devdna.core.scanner import scan_directory as scan_v1
from devdna.core.scanner2 import extract_functions, scan_directory as scan_v2

# Clean-room check: kwargs WITHOUT decorators
d = Path(tempfile.mkdtemp())
f = d / "kw.py"
f.write_text('def foo(df):\n    return df.merge(left=df, how="inner")\n')
b2 = extract_functions(f)[0]
b1 = V1(f.read_text(), f, "foo", 1)
print("no-decorator kwargs fn parity:", b1.struct_hash == b2.struct_hash)
print("  v1:", repr(b1.normalized))
print("  v2:", repr(b2.normalized))

# Repo-wide: are ALL mismatches explained purely by decorator lines?
v1 = {(str(b.filepath), b.lineno): b for b in scan_v1(Path("."))}
v2 = {(str(b.filepath), b.lineno): b for b in scan_v2(Path("."))}
unexplained = 0
for k in set(v1) & set(v2):
    if v1[k].struct_hash != v2[k].struct_hash:
        n1 = [l for l in v1[k].normalized.splitlines() if not l.lstrip().startswith("@")]
        n2 = [l for l in v2[k].normalized.splitlines() if not l.lstrip().startswith("@")]
        if n1 != n2:
            unexplained += 1
            if unexplained <= 3:
                print("UNEXPLAINED", k)
                for line in list(difflib.unified_diff(n1, n2))[:14]:
                    print("   ", line)
print(f"mismatches NOT explained by decorator lines alone: {unexplained}")
