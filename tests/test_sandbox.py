"""Tests for sandbox executor."""

import pytest
from arena.sandbox.executor import SandboxExecutor


@pytest.fixture
def executor():
    return SandboxExecutor(timeout_seconds=5, memory_mb=128)


class TestSandboxExecutor:
    """Test sandbox execution."""
    
    def test_simple_execution(self, executor):
        """Simple valid code should execute."""
        code = """
def add(a, b):
    return a + b
"""
        result = executor.execute(code, "add", args=(2, 3))
        assert result.success
        assert result.result == 5
    
    def test_zlib_decompression(self, executor):
        """zlib decompression should work."""
        import zlib
        original = b"Hello, World! " * 100
        compressed = zlib.compress(original)
        
        code = """
import zlib
def decompress(data):
    return zlib.decompress(data)
"""
        result = executor.execute(code, "decompress", args=(compressed,))
        assert result.success
        assert result.result == original
    
    def test_timeout_enforcement(self, executor):
        """Infinite loops should timeout."""
        code = """
def infinite():
    while True:
        pass
"""
        result = executor.execute(code, "infinite")
        assert not result.success
        assert "timeout" in result.error.lower()
    
    def test_forbidden_import_blocked(self, executor):
        """Forbidden imports should fail validation."""
        code = """
import os
def bad():
    return os.getcwd()
"""
        result = executor.execute(code, "bad")
        assert not result.success
        assert "ValidationError" in result.error_type
    
    def test_missing_function(self, executor):
        """Missing entry function should fail."""
        code = """
def something_else():
    return 42
"""
        result = executor.execute(code, "nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()
    
    def test_exception_handling(self, executor):
        """Exceptions in code should be caught."""
        code = """
def crasher():
    raise ValueError("intentional error")
"""
        result = executor.execute(code, "crasher")
        assert not result.success
        assert "intentional error" in result.error
        assert result.error_type == "ValueError"
    
    def test_stdout_capture(self, executor):
        """Print output should be captured."""
        code = """
def printer():
    print("hello from sandbox")
    return 42
"""
        result = executor.execute(code, "printer")
        assert result.success
        assert result.result == 42
        assert "hello from sandbox" in result.stdout
    
    def test_return_bytes(self, executor):
        """Returning bytes should work."""
        code = """
def get_bytes():
    return b'hello'
"""
        result = executor.execute(code, "get_bytes")
        assert result.success
        assert result.result == b'hello'
    
    def test_complex_compression(self, executor):
        """More complex compression code should work."""
        import zlib
        original = bytes(range(256)) * 10
        compressed = zlib.compress(original, level=9)
        
        code = """
import zlib
def decompress(data):
    return zlib.decompress(data)
"""
        result = executor.execute(code, "decompress", args=(compressed,))
        assert result.success
        assert result.result == original
    
    def test_itertools_allowed(self, executor):
        """itertools should be available."""
        code = """
import itertools
def count_perms(n):
    return len(list(itertools.permutations(range(n))))
"""
        result = executor.execute(code, "count_perms", args=(4,))
        assert result.success
        assert result.result == 24  # 4! = 24
