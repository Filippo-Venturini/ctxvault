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
    base = Path(path)
    indexed_files, skipped_files = vault.index_files(base_path=base)

    for file in indexed_files:
        typer.secho(f"Indexed: {file}", fg=typer.colors.GREEN)

    for file in skipped_files:
        typer.secho(f"Skipped: {file}", fg=typer.colors.YELLOW)

    typer.secho(f"Indexed: {len(indexed_files)}", fg=typer.colors.GREEN, bold=True)
    typer.secho(f"Skipped: {len(skipped_files)}", fg=typer.colors.YELLOW, bold=True)

@app.command()
def query(text: str = ""):
    result = vault.query(text=text)
    if not result.results:
        typer.secho("No results found.", fg=typer.colors.YELLOW)
        return

    typer.secho(f"\n Found {len(result.results)} chunks", fg=typer.colors.GREEN, bold=True)
    typer.echo("─" * 80)
    
    for idx, chunk in enumerate(result.results, 1):
        typer.secho(f"\n[{idx}] ", fg=typer.colors.CYAN, bold=True, nl=False)
        typer.secho(f"score: {chunk.score:.3f}", fg=typer.colors.MAGENTA)
        typer.secho(f"    ▸ {chunk.source} ", fg=typer.colors.BLUE, nl=False)
        typer.echo(f"(chunk {chunk.chunk_index})")

        preview = chunk.text.strip().replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:200] + "..."
        typer.echo(f"    {preview}")
    
    typer.echo("\n" + "─" * 80)

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
    documents = vault.list_documents()

    typer.secho(f"\nFound {len(documents)} documents\n", fg=typer.colors.GREEN, bold=True)

    for i in range(len(documents)):
        typer.echo(f"{i+1}. {documents[i].source} ({documents[i].chunks_count} chunks)")


def main():
    app()

if __name__ == "__main__":
    main()