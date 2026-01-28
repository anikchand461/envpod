import typer
from rich.console import Console
from rich.panel import Panel
from pathlib import Path
import yaml
import os
import subprocess
import sys
from dotenv import load_dotenv

app = typer.Typer(
    name="envpod",
    help="Local development environment synchronizer",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def find_project_root() -> Path:
    """Find nearest git root or fall back to current directory"""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").is_dir():
            return current
        current = current.parent
    return Path.cwd()


def detect_framework(project_root: Path) -> str:
    """Smart detection of run command based on files and requirements.txt"""
    reqs_path = project_root / "requirements.txt"
    deps = ""
    if reqs_path.exists():
        deps = reqs_path.read_text().lower()

    # FastAPI / Uvicorn
    if "fastapi" in deps or "uvicorn" in deps:
        if (project_root / "main.py").exists():
            return "uvicorn main:app --reload --port 8000"
        if (project_root / "app.py").exists():
            return "uvicorn app:app --reload --port 8000"

    # Flask
    if "flask" in deps:
        return "flask run --debug --port 5000"

    # Django
    if "django" in deps and (project_root / "manage.py").exists():
        return "python manage.py runserver"

    # Streamlit
    if "streamlit" in deps:
        if (project_root / "app.py").exists():
            return "streamlit run app.py"
        if (project_root / "main.py").exists():
            return "streamlit run main.py"

    # Gradio
    if "gradio" in deps:
        if (project_root / "app.py").exists():
            return "python app.py"
        if (project_root / "main.py").exists():
            return "python main.py"

    # Pytest
    if "pytest" in deps:
        return "pytest"

    # Plain Python fallback
    if (project_root / "main.py").exists():
        return "python main.py"
    if (project_root / "app.py").exists():
        return "python app.py"

    return "python -m main"  # last resort


@app.command()
def init():
    """Smart init — detects framework and creates perfect envpod.yaml"""
    project_root = find_project_root()
    console.print(f"[bold]Initializing envpod in:[/bold] {project_root}")

    config_path = project_root / "envpod.yaml"
    gitignore_path = project_root / ".gitignore"

    if config_path.exists():
        if not typer.confirm("envpod.yaml already exists. Overwrite?", default=False):
            console.print("[green]Aborted.[/green]")
            raise typer.Exit()

    # Detect Python version
    python_hint = "3.11"
    try:
        result = subprocess.run(["python", "--version"], capture_output=True, text=True, check=True)
        version_line = result.stdout.strip()
        if "Python" in version_line:
            full_ver = version_line.split()[-1]
            python_hint = ".".join(full_ver.split(".")[:2])
    except Exception:
        pass

    # Smart command detection
    run_command = detect_framework(project_root)

    config = {
        "name": project_root.name,
        "python": python_hint,
        "dependencies": {"file": "requirements.txt"} if (project_root / "requirements.txt").exists() else None,
        "env_file": ".env",
        "run": {"dev": run_command}
    }
    config = {k: v for k, v in config.items() if v is not None}

    # Write config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, sort_keys=False, allow_unicode=True)

    # .gitignore
    entry = ".envpod/"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if entry.strip() not in [line.strip() for line in content.splitlines()]:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n# envpod managed environments\n{entry}\n")
            console.print("[green]Added .envpod/ to .gitignore[/green]")
    else:
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(f"# envpod managed environments\n{entry}\n")
        console.print("[green]Created .gitignore and added .envpod/[/green]")

    console.print(Panel(
        f"[green]Smart envpod.yaml created![/green]\n"
        f"Detected command: [bold]{run_command}[/bold]\n\n"
        f"Location: {config_path}\n\n"
        f"Next:\n"
        f"  envpod up\n"
        f"  source .envpod/venv/bin/activate\n"
        f"  envpod run dev",
        title="Success",
        border_style="green"
    ))


@app.command()
def up():
    """Create virtual environment and install dependencies from envpod.yaml"""
    project_root = find_project_root()
    config_path = project_root / "envpod.yaml"

    if not config_path.exists():
        console.print("[red]envpod.yaml not found. Run 'envpod init' first.[/red]")
        raise typer.Exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    venv_dir = project_root / ".envpod" / "venv"
    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Creating venv at:[/bold] {venv_dir}")

    python_cmd = "python"  # TODO: later support pyenv/uv/etc. for version
    try:
        subprocess.run(
            [python_cmd, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True
        )
        console.print("[green]✓ Virtual environment created[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to create venv: {e.stderr.decode() or str(e)}[/red]")
        raise typer.Exit(1)

    pip_path = venv_dir / "bin" / "pip"

    # Upgrade pip + wheel
    console.print("[bold]Upgrading pip and installing wheel...[/bold]")
    subprocess.run(
        [str(pip_path), "install", "--upgrade", "pip", "wheel"],
        check=True,
        capture_output=True
    )

    # Install dependencies
    deps_file = config.get("dependencies", {}).get("file")
    if deps_file:
        deps_path = project_root / deps_file
        if deps_path.exists():
            console.print(f"[bold]Installing from[/bold] {deps_path}")
            result = subprocess.run(
                [str(pip_path), "install", "-r", str(deps_path)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                console.print("[green]✓ Dependencies installed[/green]")
            else:
                console.print(f"[red]Install failed:[/red]\n{result.stderr}")
                raise typer.Exit(1)
        else:
            console.print(f"[yellow]Dependencies file not found: {deps_path} – skipping[/yellow]")
    else:
        console.print("[yellow]No dependencies file specified[/yellow]")

    console.print(Panel(
        f"[green]Setup complete![/green]\n\n"
        f"To activate:\n  source {venv_dir}/bin/activate\n\n"
        f"Next: envpod run dev",
        title="envpod up",
        border_style="green"
    ))


@app.command()
def run(
    command_name: str = typer.Argument(..., help="Name of the command to run (e.g. dev)")
):
    """Run a named command from envpod.yaml (e.g. envpod run dev)"""
    project_root = find_project_root()
    config_path = project_root / "envpod.yaml"

    if not config_path.exists():
        console.print("[red]envpod.yaml not found. Run 'envpod init' first.[/red]")
        raise typer.Exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    run_commands = config.get("run", {})
    if not run_commands or command_name not in run_commands:
        console.print(f"[red]Command '{command_name}' not found[/red]")
        console.print(f"Available: {', '.join(run_commands.keys())}")
        raise typer.Exit(1)

    cmd = run_commands[command_name]
    console.print(f"[bold]Executing:[/bold] {cmd}")

    venv_path = project_root / ".envpod" / "venv"
    if not venv_path.exists():
        console.print("[red]Venv not found. Run 'envpod up' first.[/red]")
        raise typer.Exit(1)

    venv_python = venv_path / "bin" / "python"
    current_python = Path(sys.executable).resolve()

    # Warn if not in venv, but continue execution
    if current_python != venv_python:
        console.print("[yellow]Warning: Not in project venv — using current Python[/yellow]")
    else:
        console.print("[dim](Running in project venv)[/dim]")

    # Load .env if exists
    env_file = config.get("env_file", ".env")
    env_path = project_root / env_file
    if env_path.exists():
        load_dotenv(env_path)
        console.print("[green]Loaded .env file[/green]")
    else:
        console.print("[yellow].env file not found — skipping[/yellow]")

    # Execute the command
    try:
        result = subprocess.run(
            cmd.split(),
            cwd=project_root,
            check=True,
            capture_output=False,
            text=True
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Command failed:[/red]\n{e.stderr}")
        raise typer.Exit(1)


@app.command("doctor")
def doctor_command():
    """Check configuration and environment health (no changes made)"""
    project_root = find_project_root()
    config_path = project_root / "envpod.yaml"

    console.rule("envpod doctor", style="cyan")

    if not config_path.exists():
        console.print("[red]✗ envpod.yaml not found[/red]")
        console.print("   Run [bold]envpod init[/bold] first.")
        raise typer.Exit(1)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        console.print(f"[red]✗ Invalid YAML in {config_path}: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Config:[/bold] {config_path}")

    wanted = config.get("python", "unknown")
    console.print(f"• Python: wanted {wanted}")
    try:
        result = subprocess.run(["python", "--version"], capture_output=True, text=True)
        current = result.stdout.strip() or "not found"
        console.print(f"  Current: {current}")
        if wanted not in current:
            console.print("  [yellow]Note: minor version difference[/yellow]")
    except FileNotFoundError:
        console.print("  [red]Python not found on PATH[/red]")

    deps_file = config.get("dependencies", {}).get("file")
    if deps_file:
        p = project_root / deps_file
        if p.exists():
            console.print(f"• Dependencies file: [green]{p}[/green] exists")
        else:
            console.print(f"• Dependencies file: [red]{p} missing[/red]")
    else:
        console.print("• Dependencies: none specified")

    env_file = config.get("env_file", ".env")
    env_path = project_root / env_file
    if env_path.exists():
        console.print(f"• Env file: [green]{env_path}[/green] found")
    else:
        console.print(f"• Env file: [yellow]{env_path} missing[/yellow]")

    secrets = config.get("secrets", [])
    if secrets:
        console.print(f"• Required secrets ({len(secrets)}):")
        for key in secrets:
            if key in os.environ:
                console.print(f"  [green]✓ {key}[/green]")
            else:
                console.print(f"  [red]✗ {key}[/red]")
    else:
        console.print("• Secrets: none required")

    console.rule(style="cyan")
    console.print("[bold green]Doctor finished[/bold green]")


if __name__ == "__main__":
    app()
