from pathlib import Path
import typer
from ctxvault.core import vault
from ctxvault.core.exceptions import VaultAlreadyExistsError

app = typer.Typer()

@app.command()
def init(path: str = "."):
    try:
        typer.echo(f"Initializing Context Vault at: {path} ...")
        vault_path, config_path = vault.init_vault(path=path)
        typer.secho("Context Vault initialized succesfully!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Context Vault path: {vault_path}")
        typer.echo(f"Config file path: {config_path}")
    except VaultAlreadyExistsError as e:
        typer.secho("Warning: Context Vault already initialized in this path!", fg=typer.colors.YELLOW, bold=True)
        typer.echo(f"Existing vault path: {e.existing_path}")
        raise typer.Exit(1)

@app.command()
def index(path: str = "."):
    indexed = skipped = 0
    base = Path(path)
    for file in vault.iter_files(base):
        try:
            vault.index_file(file_path=file)
            typer.secho(f"Indexed: {file}", fg=typer.colors.GREEN)
            indexed += 1
        except Exception as e:
            typer.secho(
                f"Skipped: {file} ({e})",
                fg=typer.colors.YELLOW
            )
            skipped += 1

    typer.secho(f"Indexed: {indexed}", fg=typer.colors.GREEN, bold=True)
    typer.secho(f"Skipped: {skipped}", fg=typer.colors.YELLOW, bold=True)

@app.command()
def query(text: str = ""):
    result = vault.query(text=text)
    if not result.results:
        typer.secho("No results found.", fg=typer.colors.YELLOW)
        return

    for doc in result.results:
        typer.secho(
            f"{doc.source}  (score: {doc.score:.2f})",
            fg=typer.colors.GREEN,
            bold=True
        )

        for chunk in doc.chunks:
            typer.echo(
                f"  ├─ chunk #{chunk.chunk_index} ({chunk.score:.2f})"
            )
            preview = chunk.text.strip().replace("\n", " ")
            typer.echo(f"  │  {preview[:200]}")

        typer.echo()

@app.command()
def delete(path: str = "."):
    deleted = skipped = 0
    base = Path(path)
    for file in vault.iter_files(base):
        try:
            vault.delete_file(file_path=file)
            typer.secho(f"Deleted: {file}", fg=typer.colors.RED)
            deleted += 1
        except Exception as e:
            typer.secho(
                f"Skipped: {file} ({e})",
                fg=typer.colors.YELLOW
            )
            skipped += 1

    typer.secho(f"Deleted: {deleted}", fg=typer.colors.RED, bold=True)
    typer.secho(f"Skipped: {skipped}", fg=typer.colors.YELLOW, bold=True)

@app.command()
def reindex(path: str = "."):
    reindexed = skipped = 0
    base = Path(path)
    for file in vault.iter_files(base):
        try:
            vault.reindex_file(file_path=file)
            typer.secho(f"Reindexed: {file}", fg=typer.colors.GREEN)
            reindexed += 1
        except Exception as e:
            typer.secho(
                f"Skipped: {file} ({e})",
                fg=typer.colors.YELLOW
            )
            skipped += 1

    typer.secho(f"Reindexed: {reindexed}", fg=typer.colors.GREEN, bold=True)
    typer.secho(f"Skipped: {skipped}", fg=typer.colors.YELLOW, bold=True)

@app.command()
def sync():
    typer.echo(f"Synchronizing vault")

@app.command()
def list():
    typer.echo(f"Listing vault files")

def main():
    app()

if __name__ == "__main__":
    main()