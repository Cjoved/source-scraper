"""
One-off: move PinoyRice .txt from pinoyrice_processed/per_file to pinoyrice_txt (under data/).
Run from project root: python -m src.scripts.migrate_pinoyrice_txt
"""
import os
import shutil
from pathlib import Path

from rich.console import Console
from src.openstat.config import data_path

console = Console()

OLD_DIR = data_path("pinoyrice_processed", "per_file")
NEW_DIR = data_path("pinoyrice_txt")


def run():
    console.rule("[bold cyan]Migrate PinoyRice .txt files")
    if not os.path.isdir(OLD_DIR):
        console.print(f"[yellow]Old folder not found: {OLD_DIR}[/yellow]")
        return
    os.makedirs(NEW_DIR, exist_ok=True)

    txt_files = sorted(Path(OLD_DIR).glob("*.txt"))
    if not txt_files:
        console.print(f"[yellow]No .txt files found in {OLD_DIR}[/yellow]")
        return

    moved = 0
    for src in txt_files:
        dst = Path(NEW_DIR) / src.name
        try:
            if dst.exists():
                console.print(f"[dim]Skip (exists): {dst.name}[/dim]")
                continue
            shutil.move(str(src), str(dst))
            moved += 1
        except Exception as e:
            console.print(f"[yellow]Could not move {src.name}: {e}[/yellow]")

    console.rule("[bold green]Done")
    console.print(f"Moved files: [green]{moved}[/green]")
    console.print(f"New folder: [cyan]{NEW_DIR}[/cyan]")


if __name__ == "__main__":
    run()
