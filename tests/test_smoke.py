"""smoke tests: the entry point answers --help cleanly"""
import subprocess
import sys

PKG = "batch"


def run(*args):
    return subprocess.run([sys.executable, "-m", PKG, *args],
                          capture_output=True, text=True,
                          timeout=30)


def test_help_exits_zero():
    r = run("--help")
    assert r.returncode == 0
    assert "usage" in r.stdout.lower()
