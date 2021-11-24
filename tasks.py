"""Tasks"""
import os
import subprocess
import sys
from invoke import task
from pathlib import Path


@task
def clean(c, docs=False, bytecode=False, extra=""):
    """Clean project (linux only)"""
    patterns = ["build", "dist", "test_output"]
    if docs:
        patterns.append("docs/cli")
    if bytecode:
        patterns.append("**/*.pyc")
    if extra:
        patterns.append(extra)
    for pattern in patterns:
        c.run("rm -rf {}".format(pattern))


@task
def lint(c):
    """Lint"""
    c.run("pylint c8ylp")
    c.run("pylint tests/")


@task
def format(c, check=False):
    """Format code (using black)"""
    if check:
        c.run("black --check --target-version=py37 .")
    else:
        c.run(f"{sys.executable} -m black --target-version=py37 .")


@task
def build(c):
    """Build"""
    c.run(f"{sys.executable} setup.py build")


@task(pre=[build])
def publish(c):
    """Publish python package to pip"""
    assert "TWINE_USERNAME" in os.environ
    assert "TWINE_PASSWORD" in os.environ
    c.run("twine upload dist/*")


@task
def test(c, pattern=None):
    """Run unit tests and coverage report"""
    cmd = [
        "pytest",
        "tests",
        "--timeout=10",
        # Note: Dont use log cli level (--log-cli-level) as it can affect click testing!
        "--cov-config=.coveragerc",
        "--cov-report=term",
        "--cov-report=html:test_output/htmlcov",
        "--cov=c8ylp",
    ]

    if pattern:
        cmd.append(f"-k={pattern}")
    c.run(" ".join(cmd))


@task
def test_integration(c, pattern=None):
    """Run integration tests"""
    cmd = [
        "pytest",
        "--durations=0",
        "--timeout=3600",
        "--log-cli-level=INFO",
        "--cov-config=.coveragerc",
        "--cov-report=term",
        "--cov-report=html:test_output/htmlcov",
        "--cov=c8ylp",
    ]

    assert os.path.exists(".env") or os.environ.get(
        "C8Y_HOST"
    ), "Missing Cumulocity configuration required for integration tests"

    if pattern:
        cmd.append(f"-k={pattern}")
    c.run(" ".join(cmd))


@task
def generate_docs(c):
    """Generate cli docs (markdown files)"""
    commands = [
        ("c8ylp",),
        (
            "c8ylp",
            "login",
        ),
        (
            "c8ylp",
            "server",
        ),
        (
            "c8ylp",
            "connect",
        ),
        (
            "c8ylp",
            "connect",
            "ssh",
        ),
        (
            "c8ylp",
            "plugin",
        ),
        (
            "c8ylp",
            "plugin",
            "command",
        ),
    ]

    doc_dir = Path("docs") / "cli"
    doc_dir.mkdir(parents=True, exist_ok=True)

    for cmd in commands:
        name = "_".join(cmd).upper() + ".md"
        doc_file = doc_dir / name
        print(f"Updating cli doc: {str(doc_file)}")
        proc = subprocess.run(
            [sys.executable, "-m", *cmd, "--help"], stdout=subprocess.PIPE
        )

        usage = proc.stdout.decode().replace("python -m ", "", -1)
        doc_template = f"""
## {" ".join(cmd)}

```
{usage}
```
"""

        doc_file.write_text(doc_template)
