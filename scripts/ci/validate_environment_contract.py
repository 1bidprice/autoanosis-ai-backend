#!/usr/bin/env python3
"""Static process-level checks for Autoanosis backend environment isolation."""

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BASE = {
    "OPENAI_API_KEY": "test-openai",
    "AUTOA_AI_PROXY_SECRET": "test-proxy-secret",
    "AUTOANOSIS_IDENTITY_SECRET": "test-identity-secret",
    "AUTOA_ROLE_SYNC_SECRET": "test-role-sync-secret",
    "ADMIN_SECRET": "test-admin-secret",
}


def run_case(name, extra, should_pass):
    env = os.environ.copy()
    for key in (
        "AUTOANOSIS_ENV",
        "AUTOANOSIS_ALLOWED_ORIGINS",
        "DATABASE_URL",
        *BASE.keys(),
    ):
        env.pop(key, None)
    env.update(BASE)
    env.update(extra)

    proc = subprocess.run(
        [sys.executable, "-c", "import environment; print(environment.SETTINGS.environment)"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    passed = proc.returncode == 0
    if passed != should_pass:
        print(f"FAIL: {name}")
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(1)
    print(f"PASS: {name}")


run_case(
    "production canonical",
    {
        "AUTOANOSIS_ENV": "production",
        "AUTOANOSIS_ALLOWED_ORIGINS": "https://autoanosis.com,https://www.autoanosis.com",
        "DATABASE_URL": "postgresql://user:pass@db.example/autoanosis",
    },
    True,
)

run_case(
    "staging isolated",
    {
        "AUTOANOSIS_ENV": "staging",
        "AUTOANOSIS_ALLOWED_ORIGINS": "https://staging.example.invalid",
        "DATABASE_URL": "postgresql://user:pass@db.example/autoanosis_staging",
    },
    True,
)

run_case(
    "staging rejects production origin",
    {
        "AUTOANOSIS_ENV": "staging",
        "AUTOANOSIS_ALLOWED_ORIGINS": "https://autoanosis.com",
        "DATABASE_URL": "postgresql://user:pass@db.example/autoanosis_staging",
    },
    False,
)

run_case(
    "staging rejects sqlite",
    {
        "AUTOANOSIS_ENV": "staging",
        "AUTOANOSIS_ALLOWED_ORIGINS": "https://staging.example.invalid",
        "DATABASE_URL": "sqlite:///./unsafe.db",
    },
    False,
)

run_case(
    "production rejects missing environment",
    {
        "AUTOANOSIS_ALLOWED_ORIGINS": "https://autoanosis.com,https://www.autoanosis.com",
        "DATABASE_URL": "postgresql://user:pass@db.example/autoanosis",
    },
    False,
)

run_case(
    "staging rejects missing admin secret",
    {
        "AUTOANOSIS_ENV": "staging",
        "AUTOANOSIS_ALLOWED_ORIGINS": "https://staging.example.invalid",
        "DATABASE_URL": "postgresql://user:pass@db.example/autoanosis_staging",
        "ADMIN_SECRET": "",
    },
    False,
)

print("AUTOANOSIS BACKEND ENVIRONMENT CONTRACT: PASS")
