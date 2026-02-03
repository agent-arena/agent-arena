"""
Static code validation for sandbox security.

This is the FIRST line of defense. It performs static analysis on submitted
code to reject obviously dangerous patterns before execution.

SECURITY PRINCIPLE: Defense in depth. This validator catches obvious attacks,
but we don't rely on it alone — runtime isolation is still enforced.
"""

import ast
import re
from dataclasses import dataclass
from typing import Set, List, Optional


class ValidationError(Exception):
    """Raised when code fails validation."""
    
    def __init__(self, message: str, violations: List[str]):
        self.message = message
        self.violations = violations
        super().__init__(f"{message}: {', '.join(violations)}")


@dataclass
class ValidationResult:
    """Result of code validation."""
    valid: bool
    violations: List[str]
    imports_used: Set[str]


# Modules that are NEVER allowed
FORBIDDEN_MODULES = frozenset({
    # System access
    "os", "sys", "subprocess", "shutil", "pathlib",
    "glob", "fnmatch", "tempfile", "io",
    
    # Network
    "socket", "http", "urllib", "requests", "httpx",
    "aiohttp", "websocket", "ssl", "ftplib", "smtplib",
    "poplib", "imaplib", "telnetlib",
    
    # Process/threading (escape vectors)
    "multiprocessing", "threading", "concurrent",
    "_thread", "signal",
    
    # Code execution
    "code", "codeop", "compile", "importlib", "runpy",
    "types", "builtins", "__builtins__",
    
    # Introspection (info leak)
    "inspect", "gc", "traceback", "linecache",
    
    # Dangerous stdlib
    "ctypes", "pickle", "shelve", "marshal",
    "pty", "tty", "termios", "fcntl",
    "resource", "mmap", "sysconfig",
    
    # File access
    "fileinput", "stat", "filecmp",
})

# Modules that ARE allowed (whitelist approach for safety)
ALLOWED_MODULES = frozenset({
    # Core data structures
    "collections", "heapq", "bisect", "array",
    "dataclasses", "enum", "typing",
    
    # Math/algorithms
    "math", "cmath", "decimal", "fractions",
    "random", "statistics",
    
    # String/data processing
    "string", "re", "struct", "codecs",
    "json", "base64", "binascii", "hashlib",
    
    # Compression (core to our challenges!)
    "zlib", "gzip", "bz2", "lzma",
    
    # Iteration/functional
    "itertools", "functools", "operator",
    
    # Time (read-only, useful for algorithms)
    "time",  # Note: only time.time(), sleep is limited by timeout
    
    # Copy operations
    "copy",
})

# Dangerous built-in functions
FORBIDDEN_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__",
    "open", "input", "breakpoint",
    "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "hasattr",  # Can access __builtins__
    "memoryview",  # Can escape memory safety
})

# Dangerous attribute access patterns
FORBIDDEN_ATTRIBUTES = frozenset({
    "__class__", "__bases__", "__subclasses__",
    "__mro__", "__globals__", "__code__",
    "__builtins__", "__import__", "__loader__",
    "__spec__", "__dict__", "__slots__",
})


class CodeValidator:
    """
    Validates submitted Python code for security.
    
    Uses AST analysis to detect dangerous patterns. This is NOT a complete
    security solution — it's one layer in defense-in-depth.
    """
    
    def __init__(
        self,
        allowed_modules: Optional[Set[str]] = None,
        forbidden_modules: Optional[Set[str]] = None,
        forbidden_builtins: Optional[Set[str]] = None,
        max_code_length: int = 100_000,
    ):
        self.allowed_modules = allowed_modules or ALLOWED_MODULES
        self.forbidden_modules = forbidden_modules or FORBIDDEN_MODULES
        self.forbidden_builtins = forbidden_builtins or FORBIDDEN_BUILTINS
        self.max_code_length = max_code_length
    
    def validate(self, code: str) -> ValidationResult:
        """
        Validate Python code for security issues.
        
        Returns ValidationResult with valid=False if any issues found.
        """
        violations = []
        imports_used: Set[str] = set()
        
        # Length check
        if len(code) > self.max_code_length:
            violations.append(f"Code exceeds maximum length ({len(code)} > {self.max_code_length})")
            return ValidationResult(valid=False, violations=violations, imports_used=imports_used)
        
        # Try to parse
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            violations.append(f"Syntax error: {e}")
            return ValidationResult(valid=False, violations=violations, imports_used=imports_used)
        
        # Walk the AST
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    imports_used.add(module)
                    if module in self.forbidden_modules:
                        violations.append(f"Forbidden import: {module}")
                    elif module not in self.allowed_modules:
                        violations.append(f"Disallowed import: {module} (not in whitelist)")
            
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split('.')[0]
                    imports_used.add(module)
                    if module in self.forbidden_modules:
                        violations.append(f"Forbidden import: from {module}")
                    elif module not in self.allowed_modules:
                        violations.append(f"Disallowed import: from {module} (not in whitelist)")
            
            # Check function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.forbidden_builtins:
                        violations.append(f"Forbidden builtin: {node.func.id}()")
            
            # Check attribute access
            elif isinstance(node, ast.Attribute):
                if node.attr in FORBIDDEN_ATTRIBUTES:
                    violations.append(f"Forbidden attribute access: .{node.attr}")
            
            # Check string attribute access (e.g., getattr(x, "__class__"))
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    if node.value in FORBIDDEN_ATTRIBUTES:
                        # Only flag if it looks like it's being used for getattr-style access
                        # This catches things like: x.__dict__ via getattr(x, "__dict__")
                        violations.append(f"Suspicious string constant: '{node.value}'")
        
        # Additional regex checks for patterns AST might miss
        violations.extend(self._regex_checks(code))
        
        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            imports_used=imports_used,
        )
    
    def _regex_checks(self, code: str) -> List[str]:
        """Additional pattern-based checks."""
        violations = []
        
        # Check for attempts to access dunder methods via strings
        dunder_pattern = re.compile(r'["\']__\w+__["\']')
        if dunder_pattern.search(code):
            matches = dunder_pattern.findall(code)
            for match in matches:
                attr = match.strip("'\"")
                if attr in FORBIDDEN_ATTRIBUTES:
                    # Already caught by AST, but double-check
                    pass
        
        # Check for obvious shell injection attempts
        shell_patterns = [
            r';\s*(?:rm|cat|ls|wget|curl|nc|bash|sh|python)',
            r'\|\s*(?:sh|bash)',
            r'\$\(',
            r'`[^`]+`',
        ]
        for pattern in shell_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                violations.append(f"Suspicious shell-like pattern detected")
                break
        
        return violations
    
    def validate_or_raise(self, code: str) -> ValidationResult:
        """Validate and raise ValidationError if invalid."""
        result = self.validate(code)
        if not result.valid:
            raise ValidationError("Code validation failed", result.violations)
        return result
