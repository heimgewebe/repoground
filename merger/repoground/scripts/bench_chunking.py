import time
import sys
import os
from pathlib import Path

# Add root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))

from merger.repoground.core.chunker import Chunker

def run_benchmark():
    print("Running chunking benchmark...")

    # Generate large content (10MB)
    line = "This is a test line for benchmarking chunking performance.\n"
    content = line * 200000
    size_mb = len(content) / (1024 * 1024)
    print(f"Content size: {size_mb:.2f} MB")

    chunker = Chunker()
    file_id = "bench_file"

    start_time = time.time()
    chunks = chunker.chunk_file(file_id, content, file_path="bench_file.txt")
    end_time = time.time()

    duration = end_time - start_time
    print(f"Chunking time: {duration:.4f} seconds")
    print(f"Chunks generated: {len(chunks)}")
    print(f"Speed: {size_mb / duration:.2f} MB/s")

    # Assert performance guard (e.g. > 10 MB/s)
    # Python is slow, but chunking text should be reasonably fast.
    if duration > 2.0: # 5MB/s min
        print("WARNING: Chunking is slow!")
        if os.environ.get("BENCH_STRICT") == "1":
            sys.exit(1)
    else:
        print("Performance: OK")

if __name__ == "__main__":
    run_benchmark()
