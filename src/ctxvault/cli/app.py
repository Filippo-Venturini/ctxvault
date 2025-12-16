import typer
from ctxvault.core.vault import init_vault
from ctxvault.core.exceptions import VaultAlreadyExistsError

app = typer.Typer()

@app.command()
def init(path: str = ".data/chroma"):
    try:
        typer.echo(f"Initializing Context Vault at: {path} ...")
        vault_path, config_path = init_vault(path=path)
        typer.secho("Context Vault initialized succesfully!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Context Vault path: {vault_path}")
        typer.echo(f"Config file path: {config_path}")
    except VaultAlreadyExistsError as e:
        typer.secho("Warning: Context Vault already initialized in this path!", fg=typer.colors.YELLOW, bold=True)
        typer.echo(f"Existing vault path: {e.existing_path}")
        raise typer.Exit(1)

@app.command()
def index(path: str):
    typer.echo(f"Index file/directory: {path}")

@app.command()
def query(text: str):
    typer.echo(f"Query: {text}")

@app.command()
def delete(path: str):
    typer.echo(f"Delete file/directory: {path}")

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