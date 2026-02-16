from pathlib import Path
import typer
from ctxvault.core import vault
from ctxvault.core.exceptions import VaultAlreadyExistsError, VaultNotFoundError

app = typer.Typer()

@app.command()
def init(name: str = "vault", path: str = "."):
    try:
        typer.echo(f"Initializing Context Vault {name} at: {path} ...")
        vault_path, config_path = vault.init_vault(name=name, path=path)
        typer.secho("Context Vault initialized succesfully!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Context Vault path: {vault_path}")
        typer.echo(f"Config file path: {config_path}")
    except VaultAlreadyExistsError as e:
        typer.secho("Warning: Context Vault already initialized in this path!", fg=typer.colors.YELLOW, bold=True)
        typer.echo(f"Existing vault path: {e.existing_path}")
        raise typer.Exit(1)
    
@app.command()
def use(name: str = "vault"):
    try:
        typer.echo(f"Switching active vault to {name} ...")
        vault_path, db_path = vault.use_vault(name=name)
        typer.secho(f"Context Vault {name} is now active", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Context Vault path: {vault_path}")
        typer.echo(f"Database file path: {db_path}")
    except VaultNotFoundError as e:
        typer.secho(f"Warning: Context Vault named {name} doesn't exist!", fg=typer.colors.YELLOW, bold=True)
        raise typer.Exit(1)

@app.command()
def index(path: str = "."):
    indexed_files, skipped_files = vault.index_files(base_path=Path(path))

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
    deleted_files, skipped_files = vault.delete_files(base_path=Path(path))

    for file in deleted_files:
        typer.secho(f"Deleted: {file}", fg=typer.colors.RED)

    for file in skipped_files:
        typer.secho(f"Skipped: {file}", fg=typer.colors.YELLOW)

    typer.secho(f"Deleted: {len(deleted_files)}", fg=typer.colors.RED, bold=True)
    typer.secho(f"Skipped: {len(skipped_files)}", fg=typer.colors.YELLOW, bold=True)

@app.command()
def reindex(path: str = "."):
    reindexed_files, skipped_files = vault.reindex_files(base_path=Path(path))

    for file in reindexed_files:
        typer.secho(f"Reindexed: {file}", fg=typer.colors.GREEN)

    for file in skipped_files:
        typer.secho(f"Skipped: {file}", fg=typer.colors.YELLOW)

    typer.secho(f"Reindexed: {len(reindexed_files)}", fg=typer.colors.GREEN, bold=True)
    typer.secho(f"Skipped: {len(skipped_files)}", fg=typer.colors.YELLOW, bold=True)

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