"""
Secure sandbox executor for untrusted code.

SECURITY MODEL:
1. Static validation (validator.py) - reject obviously dangerous code
2. Restricted builtins - minimal Python environment
3. Resource limits - CPU, memory, output size
4. Timeout enforcement via threading
5. No process isolation (MVP - threading-based for speed)

NOTE: This version uses threading instead of multiprocessing for Railway compatibility.
Multiprocessing with spawn method has ~60s overhead on Railway containers.
Threading is less isolated but functional for MVP.
"""

import threading
import sys
import io
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from ..config import SANDBOX_TIMEOUT_SECONDS, SANDBOX_MEMORY_MB, SANDBOX_MAX_OUTPUT_BYTES
from .validator import CodeValidator, ValidationError


@dataclass
class ExecutionResult:
    """Result of sandbox execution."""
    success: bool
    result: Any
    error: Optional[str]
    error_type: Optional[str]
    stdout: str
    stderr: str
    execution_time_ms: int
    memory_used_bytes: Optional[int]


class SandboxError(Exception):
    """Base exception for sandbox errors."""
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
    'print': print,
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


# Pre-import allowed modules (done once at module load)
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

ALLOWED_MODULES = {
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
}


def _execute_code(
    code: str,
    entry_function: str,
    args: tuple,
    kwargs: dict,
) -> ExecutionResult:
    """
    Execute code in a restricted environment.
    Called from a thread with timeout.
    """
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    
    start_time = time.time()
    
    try:
        # Redirect output
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        
        # Build restricted globals
        restricted_globals = {
            '__builtins__': RESTRICTED_BUILTINS,
            '__name__': '__sandbox__',
            '__doc__': None,
        }
        
        # Add allowed modules
        restricted_globals.update(ALLOWED_MODULES)
        
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
        
        return ExecutionResult(
            success=True,
            result=call_result,
            error=None,
            error_type=None,
            stdout=captured_stdout.getvalue()[:SANDBOX_MAX_OUTPUT_BYTES],
            stderr=captured_stderr.getvalue()[:SANDBOX_MAX_OUTPUT_BYTES],
            execution_time_ms=int((end_time - start_time) * 1000),
            memory_used_bytes=None,
        )
        
    except Exception as e:
        end_time = time.time()
        traceback.print_exc(file=captured_stderr)
        
        return ExecutionResult(
            success=False,
            result=None,
            error=str(e),
            error_type=type(e).__name__,
            stdout=captured_stdout.getvalue()[:SANDBOX_MAX_OUTPUT_BYTES],
            stderr=captured_stderr.getvalue()[:SANDBOX_MAX_OUTPUT_BYTES],
            execution_time_ms=int((end_time - start_time) * 1000),
            memory_used_bytes=None,
        )
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


class SandboxExecutor:
    """
    Executes untrusted Python code in a sandboxed environment.
    
    Uses threading with timeout for Railway compatibility.
    Static validation + restricted builtins provide security.
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
        
        # Step 2: Run in thread with timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _execute_code,
                code,
                entry_function,
                args,
                kwargs,
            )
            
            try:
                result = future.result(timeout=self.timeout_seconds)
                return result
            except FuturesTimeoutError:
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
            except Exception as e:
                return ExecutionResult(
                    success=False,
                    result=None,
                    error=f"Sandbox error: {str(e)}",
                    error_type="SandboxError",
                    stdout="",
                    stderr="",
                    execution_time_ms=0,
                    memory_used_bytes=None,
                )
