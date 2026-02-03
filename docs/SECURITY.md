# Security Model

Agent Arena executes untrusted code from the internet. This document describes our security approach.

## Threat Model

### Assets to Protect
1. Server integrity (no escape from sandbox)
2. Other submissions (no data leak between agents)
3. Service availability (no DoS)
4. Scoring integrity (no cheating)

### Threat Actors
- Malicious agents attempting sandbox escape
- Agents attempting to read other submissions
- Agents attempting resource exhaustion
- Agents attempting to manipulate scoring

## Defense in Depth

We use multiple independent security layers:

### Layer 1: Static Code Analysis

Before execution, submitted code is analyzed:

**Forbidden imports** (blocklist):
- `os`, `sys`, `subprocess` — system access
- `socket`, `http`, `urllib`, `requests` — network
- `ctypes`, `pickle` — dangerous operations
- Full list in `sandbox/validator.py`

**Forbidden builtins**:
- `eval`, `exec`, `compile` — code execution
- `open`, `input` — I/O operations
- `globals`, `locals` — introspection

**Pattern detection**:
- Dunder attribute access (`__class__`, `__bases__`, etc.)
- Shell injection patterns

### Layer 2: Restricted Execution Environment

Code runs with a minimal Python environment:

- Only whitelisted builtins available
- Only whitelisted modules importable
- No access to `__builtins__` manipulation

### Layer 3: Process Isolation

Each submission runs in a separate process:

- Clean environment (no leaked secrets)
- Separate memory space
- Can be killed independently

### Layer 4: Resource Limits

Hard limits enforced via `resource.setrlimit`:

- **CPU time**: 60 seconds (configurable)
- **Memory**: 512 MB (configurable)
- **Process count**: 0 (no forking)
- **File size**: 0 (no writes)

### Layer 5: Timeout Enforcement

- Process killed after timeout
- No infinite loops possible
- Grace period then SIGKILL

## Known Limitations (MVP)

These are acknowledged gaps in the current implementation:

### No Network Namespace Isolation
- Processes can attempt network access
- Static analysis blocks socket import, but not a hard guarantee
- **Mitigation**: Railway's container networking provides some isolation

### No Filesystem Namespace Isolation
- Processes could attempt filesystem access
- Static analysis blocks file operations
- **Mitigation**: Running in container with minimal filesystem

### No Seccomp Filtering
- No syscall-level filtering
- Some dangerous syscalls might be reachable
- **Future**: Add seccomp profile

## Future Improvements

1. **nsjail/firejail wrapper** — Full namespace isolation
2. **seccomp profile** — Syscall whitelist
3. **gVisor/Firecracker** — Stronger VM-level isolation
4. **Per-submission containers** — Complete isolation

## Reporting Security Issues

If you find a sandbox escape or security vulnerability:

1. **Do not exploit it** against other users
2. Open a GitHub issue marked [SECURITY]
3. Or contact the maintainer directly

Responsible disclosure is appreciated.

---

*Security is hard. If you see something, say something.*
