from pathlib import Path
from ctxvault.models.documents import SemanticDocumentInfo, SkillDocumentInfo
from ctxvault.models.vaults import VaultType
import typer
from ctxvault.core import vault_router
from ctxvault.core.exceptions import PathOutsideVaultError, VaultAlreadyExistsError, VaultNotFoundError, VaultTypeNotValidError

app = typer.Typer()

def _print_vault(v: dict):
    name = v['name']
    vault_type = v.get("type", "semantic")
    is_restricted = v.get("restricted", False)
    allowed_agents = v.get("allowed_agents", [])

    typer.secho(f"  {name:<20}", bold=True, nl=False)

    if vault_type == "skill":
        typer.secho("[SKILL]    ", fg=typer.colors.MAGENTA, bold=True, nl=False)
    else:
        typer.secho("[SEMANTIC] ", fg=typer.colors.CYAN, bold=True, nl=False)

    if is_restricted:
        typer.secho("[RESTRICTED]", fg=typer.colors.YELLOW, bold=True, nl=False)
        if allowed_agents:
            typer.secho(f"  agents: {', '.join(allowed_agents)}", fg=typer.colors.YELLOW, nl=False)
        else:
            typer.secho("  agents: none authorized yet", fg=typer.colors.YELLOW, nl=False)
    else:
        typer.secho("[PUBLIC]", fg=typer.colors.GREEN, bold=True, nl=False)

    typer.echo("")
    typer.secho(f"  {'path:':<20}{v['vault_path']}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo("")

@app.command()
def init(name: str = typer.Argument("my-vault"), type: str = typer.Option(VaultType.SEMANTIC.value, "--type"), restricted: bool = typer.Option(False, "--restricted"), path: str = typer.Option(None, "--path"), global_vault: bool = typer.Option(False, "--global")):
    try:
        typer.echo(f"Initializing Context Vault {name}...")
        vault_path, config_path = vault_router.init_vault(vault_name=name, vault_type=type, restricted=restricted, path=path, global_vault=global_vault)
        typer.secho("Context Vault initialized succesfully!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"Context Vault path: {vault_path}")
        typer.echo(f"Config file path: {config_path}")
    except Exception as e:
        typer.secho(f"Error during initialization: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def index(name: str = typer.Argument("my-vault"), path: str = typer.Option(None, "--path")):
    try:
        indexed_files, skipped_files = vault_router.index_files(vault_name=name, path=path)

        for file in indexed_files:
            typer.secho(f"Indexed: {file}", fg=typer.colors.GREEN)

        for file in skipped_files:
            typer.secho(f"Skipped: {file}", fg=typer.colors.YELLOW)

        typer.secho(f"\nIndexed: {len(indexed_files)}", fg=typer.colors.GREEN, bold=True)
        typer.secho(f"Skipped: {len(skipped_files)}", fg=typer.colors.YELLOW, bold=True)
    except Exception as e:
        typer.secho(f"Error during indexing: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    
@app.command()
def query(name: str = typer.Argument("my-vault"), text: str = typer.Argument("")):
    try:
        result = vault_router.query(text=text, vault_name=name)
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
    except Exception as e:
        typer.secho(f"Error during querying: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def delete(name: str = typer.Argument("my-vault"), path: str = typer.Option(None, "--path"), purge: bool = typer.Option(False, "--purge")):
    if purge and path:
        typer.secho("Error: --purge and --path are mutually exclusive.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    try:
        if purge:
            vault_router.purge_vault(vault_name=name)
            typer.secho(f"Vault '{name}' permanently deleted.", fg=typer.colors.RED, bold=True)
            return
        
        deleted_files, skipped_files = vault_router.delete_files(vault_name=name, path=path)

        for file in deleted_files:
            typer.secho(f"Deleted: {file}", fg=typer.colors.RED)

        for file in skipped_files:
            typer.secho(f"Skipped: {file}", fg=typer.colors.YELLOW)

        typer.secho(f"Deleted: {len(deleted_files)}", fg=typer.colors.RED, bold=True)
        typer.secho(f"Skipped: {len(skipped_files)}", fg=typer.colors.YELLOW, bold=True)
    except Exception as e:
        typer.secho(f"Error during deleting: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def reindex(name: str = typer.Argument("my-vault"), path: str = typer.Option(None, "--path")):
    try:
        reindexed_files, skipped_files = vault_router.reindex_files(vault_name=name, path=path)

        for file in reindexed_files:
            typer.secho(f"Reindexed: {file}", fg=typer.colors.GREEN)

        for file in skipped_files:
            typer.secho(f"Skipped: {file}", fg=typer.colors.YELLOW)

        typer.secho(f"Reindexed: {len(reindexed_files)}", fg=typer.colors.GREEN, bold=True)
        typer.secho(f"Skipped: {len(skipped_files)}", fg=typer.colors.YELLOW, bold=True)
    except Exception as e:
        typer.secho(f"Error during reindexing: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def vaults():
    vaults_list = vault_router.list_vaults()

    local_vaults = [v for v in vaults_list if v.get("scope") == "local"]
    global_vaults = [v for v in vaults_list if v.get("scope") == "global"]

    typer.secho(f"\nFound {len(vaults_list)} vaults ({len(local_vaults)} local, {len(global_vaults)} global)\n", fg=typer.colors.GREEN, bold=True)

    if local_vaults:
        typer.secho("── local ────────────────────────────────────────────────────────", fg=typer.colors.CYAN, bold=True)
        for v in local_vaults:
            _print_vault(v)

    if global_vaults:
        typer.secho("── global ───────────────────────────────────────────────────────", fg=typer.colors.CYAN, bold=True)
        for v in global_vaults:
            _print_vault(v)

@app.command()
def docs(
    name: str = typer.Argument("my-vault"),
    export: str | None = typer.Option(None, "--export", help="Document id to export (requires --output)"),
    show: str | None = typer.Option(None, "--show", help="Document id to display reconstructed text for"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write exported content to this file"),
    json_output: bool = typer.Option(False, "--json", help="Print metadata and content as JSON"),
):
    if export and show:
        typer.secho("Error: --export and --show are mutually exclusive.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)
    if export:
        if not output:
            typer.secho("Error: --export requires --output.", fg=typer.colors.RED, bold=True)
            raise typer.Exit(1)
        _doc_content_command(name, export, output=output, json_output=json_output)
        return
    if show:
        _doc_content_command(name, show, output=output, json_output=json_output)
        return
    if output or json_output:
        typer.secho("Error: --output and --json require --export or --show.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

    try:
        documents = vault_router.list_documents(vault_name=name)

        typer.secho(f"\nFound {len(documents)} documents in '{name}'\n", fg=typer.colors.GREEN, bold=True)

        for i, doc in enumerate(documents, 1):
            typer.echo(f"  {i}. ", nl=False)
            filename = Path(doc.source).name
            typer.secho(f"{filename}", bold=True)

            info_line = f"     {doc.filetype} · {doc.chunks_count} chunks · ID: {doc.doc_id}"
            typer.secho(info_line, fg=typer.colors.BRIGHT_BLACK)

            typer.echo("")

    except Exception as e:
        typer.secho(f"Error during document listing: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

def _render_doc_content(doc, *, json_output: bool = False):
    if json_output:
        typer.echo(doc.model_dump_json(indent=2))
        return

    typer.secho(f"Document ID: {doc.doc_id}", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"Source: {doc.source}", fg=typer.colors.BLUE)
    typer.secho(
        f"Type: {doc.filetype} · Chunks: {doc.chunks_count} · Hash: {doc.reconstructed_text_hash}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if doc.indexed_at:
        typer.secho(f"Indexed at: {doc.indexed_at}", fg=typer.colors.BRIGHT_BLACK)
    if doc.warning:
        typer.secho(f"Warning: {doc.warning}", fg=typer.colors.YELLOW)
    typer.echo("─" * 80)
    typer.echo(doc.content)

def _doc_content_command(
    name: str,
    doc_id: str,
    output: Path | None = None,
    json_output: bool = False,
):
    try:
        doc = vault_router.get_document_content(vault_name=name, doc_id=doc_id)
        if output:
            output.write_text(doc.content, encoding="utf-8")
            typer.secho(f"Exported indexed text to {output}", fg=typer.colors.GREEN, bold=True)
            if doc.warning:
                typer.secho(doc.warning, fg=typer.colors.YELLOW)
            return

        _render_doc_content(doc, json_output=json_output)
    except Exception as e:
        typer.secho(f"Error retrieving document content: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def attach(vault_name: str = typer.Argument("my-vault"), agent_name: str = typer.Argument(...)):
    try:
        typer.echo(f"Attaching agent {agent_name} to vault {vault_name}...")

        vault_router.attach_agent(vault_name=vault_name, agent_name=agent_name)

        typer.secho(f"Agent {agent_name} attached to vault {vault_name} successfully!", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"Error during agent attachment: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def detach(vault_name: str = typer.Argument("my-vault"), agent_name: str = typer.Argument(...)):
    try:
        typer.echo(f"Detaching agent {agent_name} from vault {vault_name}...")

        vault_router.detach_agent(vault_name=vault_name, agent_name=agent_name)

        typer.secho(f"Agent {agent_name} detached from vault {vault_name} successfully!", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"Error during agent detachment: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def publish(vault_name: str = typer.Argument("my-vault")):
    try:
        typer.echo(f"Making {vault_name} public...")

        vault_router.make_public(vault_name=vault_name)

        typer.secho(f"Vault {vault_name} is now public!", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"Error during vault publishing: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def skills(name: str = typer.Argument("my-vault")):
    try:
        skills = vault_router.list_skills(vault_name=name)

        typer.secho(f"\nFound {len(skills)} skills in '{name}'\n", fg=typer.colors.GREEN, bold=True)

        for i, skill in enumerate(skills, 1):
            typer.echo(f"  {i}. ", nl=False)

            typer.secho(f"{skill.skill_name}", bold=True)
            typer.secho(f"     Type: Skill (.md) · Last Mod: {skill.last_modified}", fg=typer.colors.BRIGHT_BLACK)
            if skill.description:
                typer.secho(f"     Description: {skill.description}", fg=typer.colors.CYAN, italic=True)

            typer.echo("")

    except Exception as e:
        typer.secho(f"Error during document listing: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)

@app.command()
def skill(vault_name: str = typer.Argument(...), skill_name: str = typer.Argument(...)):
    try:
        skill = vault_router.read_skill(vault_name=vault_name, skill_name=skill_name)

        typer.echo("-" * 100)
        typer.secho(f"SKILL: {skill.name}", fg=typer.colors.CYAN, bold=True)
        if skill.description:
            typer.secho(f"Description: {skill.description}", fg=typer.colors.YELLOW)
        typer.echo("-" * 100)

        if skill.metadata:
            for key, value in skill.metadata.items():
                if key not in ['name', 'description']:
                    typer.secho(f"{key}: ", fg=typer.colors.BRIGHT_BLACK, nl=False)
                    typer.echo(f"{value}")
            typer.echo("-" * 100)

        typer.echo(skill.instructions)
        typer.echo("")

    except Exception as e:
        typer.secho(f"Error reading skill: {e}", fg=typer.colors.RED, bold=True)
        raise typer.Exit(1)


def main():
    app()

if __name__ == "__main__":
    main()