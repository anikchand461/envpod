import typer
from rich.console import Console
from rich.panel import Panel
from pathlib import Path
import yaml
import os
import subprocess

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
    return Path.cwd()  # fallback


@app.command()
def init():
    """Initialize envsync.yaml for current project"""
    project_root = find_project_root()
    console.print(f"[bold]Initializing envsync in:[/bold] {project_root}")

    config_path = project_root / "envsync.yaml"
    gitignore_path = project_root / ".gitignore"

    if config_path.exists():
        if not typer.confirm("envsync.yaml already exists. Overwrite?", default=False):
            console.print("[green]Aborted.[/green]")
            raise typer.Exit()

    # Detection
    has_reqs = (project_root / "requirements.txt").exists()

    # Detect current Python version (major.minor)
    python_hint = "3.11"  # fallback
    try:
        result = subprocess.run(
            ["python", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        version_line = result.stdout.strip()
        if "Python" in version_line:
            full_ver = version_line.split()[-1]
            python_hint = ".".join(full_ver.split(".")[:2])
    except Exception:
        pass

    # Simple run command guess
    guessed_run = "python main.py"
    if (project_root / "main.py").exists():
        guessed_run = "python main.py"
    elif (project_root / "app.py").exists():
        guessed_run = "python app.py"

    config = {
        "name": project_root.name,
        "python": python_hint,
        "dependencies": {"file": "requirements.txt"} if has_reqs else None,
        "env_file": ".env",
        "run": {"dev": guessed_run}
    }
    config = {k: v for k, v in config.items() if v is not None}

    # Write config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, sort_keys=False, allow_unicode=True)

    # Handle .gitignore
    gitignore_entry = ".envsync/"
    if gitignore_path.exists():
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        stripped_lines = [line.strip() for line in lines]
        if gitignore_entry.strip() not in stripped_lines:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write(f"\n# envsync managed environments\n{gitignore_entry}\n")
            console.print("[green]Added .envsync/ to .gitignore[/green]")
        else:
            console.print("[dim].envsync/ already in .gitignore[/dim]")
    else:
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(f"# envsync managed environments\n{gitignore_entry}\n")
        console.print("[green]Created .gitignore and added .envsync/[/green]")

    console.print(Panel(
        f"[green]Created/updated envsync.yaml[/green]\n"
        f"Location: {config_path}\n\n"
        f"Next steps:\n"
        f"  envsync doctor\n"
        f"  envsync up\n"
        f"  envsync run dev",
        title="Success",
        border_style="green"
    ))


@app.command()
def up():
    """Create virtual environment and install dependencies from envsync.yaml"""
    project_root = find_project_root()
    config_path = project_root / "envsync.yaml"

    if not config_path.exists():
        console.print("[red]envsync.yaml not found. Run 'envsync init' first.[/red]")
        raise typer.Exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    venv_dir = project_root / ".envsync" / "venv"
    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Creating venv at:[/bold] {venv_dir}")

    python_cmd = "python"  # TODO: later support specific version
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
        f"Next: envsync run dev",
        title="envsync up",
        border_style="green"
    ))


@app.command()
def run(
    command_name: str = typer.Argument(
        ..., help="Name of the command to run (e.g. dev)"
    )
):
    """Run a named command from envsync.yaml (e.g. envsync run dev)"""
    project_root = find_project_root()
    config_path = project_root / "envsync.yaml"

    if not config_path.exists():
        console.print("[red]envsync.yaml not found. Run 'envsync init' first.[/red]")
        raise typer.Exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    run_commands = config.get("run", {})
    if not run_commands:
        console.print("[red]No 'run' section found in envsync.yaml[/red]")
        raise typer.Exit(1)

    if command_name not in run_commands:
        console.print(f"[red]Command '{command_name}' not found[/red]")
        console.print(f"Available: {', '.join(run_commands.keys())}")
        raise typer.Exit(1)

    cmd = run_commands[command_name]
    console.print(f"[bold]Would run:[/bold] {cmd}")

    console.print(Panel(
        "[yellow]Command execution not fully implemented yet[/yellow]\n\n"
        f"Next steps:\n"
        f"• Activate venv\n"
        f"• Load .env\n"
        f"• Execute: {cmd}",
        title=f"envsync run {command_name}",
        border_style="yellow"
    ))


@app.command("doctor")
def doctor_command():
    """Check configuration and environment health (no changes made)"""
    project_root = find_project_root()
    config_path = project_root / "envsync.yaml"

    console.rule("envsync doctor", style="cyan")

    if not config_path.exists():
        console.print("[red]✗ envsync.yaml not found[/red]")
        console.print("   Run [bold]envsync init[/bold] first.")
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
