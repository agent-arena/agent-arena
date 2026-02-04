"""
Secure sandbox executor for untrusted code.

SECURITY MODEL:
1. Static validation (validator.py) - reject obviously dangerous code
2. Restricted builtins - minimal Python environment
3. Resource limits - CPU, memory, output size
4. Process isolation - separate interpreter, clean environment
5. Timeout enforcement - hard kill on timeout

LIMITATIONS (MVP):
- No namespace isolation (would need nsjail/bubblewrap for production)
- No network isolation (would need iptables/unshare for production)
- Relies on static analysis catching dangerous patterns

FUTURE IMPROVEMENTS:
- Add nsjail or firejail wrapper
- Add seccomp syscall filtering
- Add network namespace isolation
- Run as unprivileged user in container
"""

import multiprocessing
import resource
import signal
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable
import hashlib

# CRITICAL: Use 'spawn' instead of 'fork' to avoid deadlocks with threaded servers
# The default 'fork' method copies memory but not threads, leaving locks in acquired state
# See: https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass  # Already set, ignore

from ..config import SANDBOX_TIMEOUT_SECONDS, SANDBOX_MEMORY_MB, SANDBOX_MAX_OUTPUT_BYTES
from .validator import CodeValidator, ValidationError


@dataclass
class ExecutionResult:
    """Result of sandbox execution."""
    success: bool
    result: Any  # The return value if success
    error: Optional[str]  # Error message if failed
    error_type: Optional[str]  # Exception type if failed
    stdout: str
    stderr: str
    execution_time_ms: int
    memory_used_bytes: Optional[int]


class SandboxError(Exception):
    """Base exception for sandbox errors."""
    pass


class TimeoutError(SandboxError):
    """Execution exceeded time limit."""
    pass


class MemoryError(SandboxError):
    """Execution exceeded memory limit."""
    pass


class OutputLimitError(SandboxError):
    """Output exceeded size limit."""
    pass


# Restricted builtins - absolute minimum needed for computation
RESTRICTED_BUILTINS = {
    # Types
    'None': None,
    'True': True,
    'False': False,
    'int': int,
    'float': float,
    'bool': bool,
    'str': str,
    'bytes': bytes,
    'bytearray': bytearray,
    'list': list,
    'tuple': tuple,
    'dict': dict,
    'set': set,
    'frozenset': frozenset,
    
    # Functions
    'abs': abs,
    'all': all,
    'any': any,
    'bin': bin,
    'chr': chr,
    'divmod': divmod,
    'enumerate': enumerate,
    'filter': filter,
    'hex': hex,
    'isinstance': isinstance,
    'issubclass': issubclass,
    'iter': iter,
    'len': len,
    'map': map,
    'max': max,
    'min': min,
    'next': next,
    'oct': oct,
    'ord': ord,
    'pow': pow,
    'print': print,  # Captured to stdout
    'range': range,
    'repr': repr,
    'reversed': reversed,
    'round': round,
    'slice': slice,
    'sorted': sorted,
    'sum': sum,
    'zip': zip,
    
    # Exceptions (read-only, for catching)
    'Exception': Exception,
    'ValueError': ValueError,
    'TypeError': TypeError,
    'KeyError': KeyError,
    'IndexError': IndexError,
    'RuntimeError': RuntimeError,
    'StopIteration': StopIteration,
    'ZeroDivisionError': ZeroDivisionError,
    'OverflowError': OverflowError,
}


def _set_resource_limits(memory_mb: int, cpu_seconds: int):
    """Set resource limits for the current process (Linux only)."""
    try:
        # Memory limit (in bytes)
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        
        # CPU time limit
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        
        # Prevent forking
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        
        # Limit file size (no large files)
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        
        # Limit core dump (no core files)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        
    except (ValueError, resource.error) as e:
        # Resource limits may not be available on all systems
        print(f"Warning: Could not set resource limits: {e}", file=sys.stderr)


def _run_in_sandbox(
    code: str,
    entry_function: str,
    args: tuple,
    kwargs: dict,
    memory_mb: int,
    cpu_seconds: int,
    result_queue: multiprocessing.Queue,
):
    """
    Run code in a sandboxed subprocess.
    
    This function runs in a separate process with resource limits.
    """
    import io
    import time
    
    # Capture stdout/stderr
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    
    result = ExecutionResult(
        success=False,
        result=None,
        error=None,
        error_type=None,
        stdout="",
        stderr="",
        execution_time_ms=0,
        memory_used_bytes=None,
    )
    
    try:
        # Set resource limits BEFORE executing any user code
        _set_resource_limits(memory_mb, cpu_seconds)
        
        # Redirect output
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        
        # Build restricted globals
        restricted_globals = {
            '__builtins__': RESTRICTED_BUILTINS,
            '__name__': '__sandbox__',
            '__doc__': None,
        }
        
        # Allow specific safe imports
        # These are added to globals so import statements work
        import zlib
        import gzip
        import bz2
        import lzma
        import hashlib
        import base64
        import struct
        import json
        import math
        import itertools
        import functools
        import collections
        import heapq
        import bisect
        import re
        import copy
        import time as time_module
        
        # Add allowed modules to globals
        allowed_imports = {
            'zlib': zlib,
            'gzip': gzip,
            'bz2': bz2,
            'lzma': lzma,
            'hashlib': hashlib,
            'base64': base64,
            'struct': struct,
            'json': json,
            'math': math,
            'itertools': itertools,
            'functools': functools,
            'collections': collections,
            'heapq': heapq,
            'bisect': bisect,
            're': re,
            'copy': copy,
            'time': time_module,
        }
        restricted_globals.update(allowed_imports)
        
        start_time = time.time()
        
        # Execute the code to define functions
        exec(code, restricted_globals)
        
        # Check the entry function exists
        if entry_function not in restricted_globals:
            raise ValueError(f"Entry function '{entry_function}' not found in code")
        
        func = restricted_globals[entry_function]
        if not callable(func):
            raise ValueError(f"'{entry_function}' is not callable")
        
        # Call the entry function
        call_result = func(*args, **kwargs)
        
        end_time = time.time()
        
        result.success = True
        result.result = call_result
        result.execution_time_ms = int((end_time - start_time) * 1000)
        
    except MemoryError:
        result.error = "Memory limit exceeded"
        result.error_type = "MemoryError"
    except Exception as e:
        result.error = str(e)
        result.error_type = type(e).__name__
        # Include traceback in stderr for debugging
        traceback.print_exc(file=captured_stderr)
    finally:
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
        # Capture output (with size limits)
        result.stdout = captured_stdout.getvalue()[:SANDBOX_MAX_OUTPUT_BYTES]
        result.stderr = captured_stderr.getvalue()[:SANDBOX_MAX_OUTPUT_BYTES]
    
    # Send result back
    try:
        result_queue.put(result, timeout=5)
    except Exception:
        pass  # Process might be killed


class SandboxExecutor:
    """
    Executes untrusted Python code in a sandboxed environment.
    
    Usage:
        executor = SandboxExecutor()
        result = executor.execute(
            code="def decompress(data): return zlib.decompress(data)",
            entry_function="decompress",
            args=(compressed_data,),
        )
    """
    
    def __init__(
        self,
        timeout_seconds: int = SANDBOX_TIMEOUT_SECONDS,
        memory_mb: int = SANDBOX_MEMORY_MB,
        validate: bool = True,
    ):
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.validate = validate
        self.validator = CodeValidator()
    
    def execute(
        self,
        code: str,
        entry_function: str,
        args: tuple = (),
        kwargs: Optional[Dict] = None,
    ) -> ExecutionResult:
        """
        Execute code in sandbox and return result.
        
        Args:
            code: Python code to execute
            entry_function: Name of function to call after exec()
            args: Positional arguments to pass to entry function
            kwargs: Keyword arguments to pass to entry function
        
        Returns:
            ExecutionResult with success status, result/error, and captured output
        """
        kwargs = kwargs or {}
        
        # Step 1: Validate code statically
        if self.validate:
            try:
                self.validator.validate_or_raise(code)
            except ValidationError as e:
                return ExecutionResult(
                    success=False,
                    result=None,
                    error=str(e),
                    error_type="ValidationError",
                    stdout="",
                    stderr="",
                    execution_time_ms=0,
                    memory_used_bytes=None,
                )
        
        # Step 2: Run in isolated subprocess using spawn context
        # Spawn is safer than fork in threaded environments (FastAPI/uvicorn)
        ctx = multiprocessing.get_context('spawn')
        result_queue = ctx.Queue()
        
        process = ctx.Process(
            target=_run_in_sandbox,
            args=(
                code,
                entry_function,
                args,
                kwargs,
                self.memory_mb,
                self.timeout_seconds,
                result_queue,
            ),
        )
        
        process.start()
        process.join(timeout=self.timeout_seconds + 5)  # Extra grace period
        
        if process.is_alive():
            # Process didn't finish in time - kill it
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
            
            return ExecutionResult(
                success=False,
                result=None,
                error=f"Execution timeout ({self.timeout_seconds}s)",
                error_type="TimeoutError",
                stdout="",
                stderr="",
                execution_time_ms=self.timeout_seconds * 1000,
                memory_used_bytes=None,
            )
        
        # Get result from queue
        try:
            result = result_queue.get(timeout=1)
            return result
        except Exception:
            return ExecutionResult(
                success=False,
                result=None,
                error="Failed to get result from sandbox",
                error_type="SandboxError",
                stdout="",
                stderr="",
                execution_time_ms=0,
                memory_used_bytes=None,
            )
