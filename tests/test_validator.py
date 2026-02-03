"""Tests for code validator."""

import pytest
from arena.sandbox.validator import CodeValidator, ValidationError


@pytest.fixture
def validator():
    return CodeValidator()


class TestCodeValidator:
    """Test static code validation."""
    
    def test_valid_simple_code(self, validator):
        """Valid code should pass."""
        code = """
def decompress(data):
    import zlib
    return zlib.decompress(data)
"""
        result = validator.validate(code)
        assert result.valid
        assert len(result.violations) == 0
    
    def test_forbidden_os_import(self, validator):
        """os import should be blocked."""
        code = """
import os
def decompress(data):
    return data
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("os" in v for v in result.violations)
    
    def test_forbidden_subprocess(self, validator):
        """subprocess import should be blocked."""
        code = """
import subprocess
def decompress(data):
    return data
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("subprocess" in v for v in result.violations)
    
    def test_forbidden_socket(self, validator):
        """socket import should be blocked."""
        code = """
import socket
def decompress(data):
    return data
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("socket" in v for v in result.violations)
    
    def test_forbidden_eval(self, validator):
        """eval() should be blocked."""
        code = """
def decompress(data):
    return eval(data)
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("eval" in v for v in result.violations)
    
    def test_forbidden_exec(self, validator):
        """exec() should be blocked."""
        code = """
def decompress(data):
    exec(data)
    return b''
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("exec" in v for v in result.violations)
    
    def test_forbidden_open(self, validator):
        """open() should be blocked."""
        code = """
def decompress(data):
    with open('/etc/passwd') as f:
        return f.read().encode()
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("open" in v for v in result.violations)
    
    def test_forbidden_dunder_class(self, validator):
        """__class__ access should be blocked."""
        code = """
def decompress(data):
    return data.__class__.__bases__[0]
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("__class__" in v or "__bases__" in v for v in result.violations)
    
    def test_allowed_zlib(self, validator):
        """zlib should be allowed."""
        code = """
import zlib
def decompress(data):
    return zlib.decompress(data)
"""
        result = validator.validate(code)
        assert result.valid
        assert "zlib" in result.imports_used
    
    def test_allowed_math(self, validator):
        """math should be allowed."""
        code = """
import math
def decompress(data):
    return bytes([int(math.sqrt(x)) for x in data])
"""
        result = validator.validate(code)
        assert result.valid
        assert "math" in result.imports_used
    
    def test_syntax_error(self, validator):
        """Syntax errors should fail validation."""
        code = """
def decompress(data)
    return data
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("Syntax error" in v for v in result.violations)
    
    def test_code_length_limit(self, validator):
        """Very long code should fail."""
        code = "x = 1\n" * 100001  # Exceeds 100KB
        result = validator.validate(code)
        assert not result.valid
        assert any("length" in v.lower() for v in result.violations)
    
    def test_from_import_forbidden(self, validator):
        """from X import should also be blocked for forbidden modules."""
        code = """
from os import path
def decompress(data):
    return data
"""
        result = validator.validate(code)
        assert not result.valid
        assert any("os" in v for v in result.violations)
    
    def test_validate_or_raise(self, validator):
        """validate_or_raise should raise ValidationError."""
        code = """
import os
def decompress(data):
    return data
"""
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_or_raise(code)
        assert "os" in str(exc_info.value)
