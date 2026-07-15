#!/usr/bin/env python3
"""Generate a Fernet key, installing cryptography if necessary."""
try:
    from cryptography.fernet import Fernet
except ImportError:
    import subprocess
    import sys

    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "cryptography"]
    )
    from cryptography.fernet import Fernet

print(Fernet.generate_key().decode())
