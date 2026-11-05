"""The memory, looked at.

`ctxvault ui` opens a browser on every registered vault: which ones exist,
what type they are, who may reach them, and what is inside. A semantic vault
shows its documents, a skill vault its skills, an episodic vault what holds
now, what held at any past instant, and how each statement got where it is.
Everything is read-only: the page observes, the agents and the CLI write.

The page reads the vaults through the core, the way the CLI does, so it sees
what was written through any door: CLI, Python client, HTTP API or MCP. It
never reaches past the vault classes into the stores: what it shows is what
the library exposes, shaped for a page. A browser needs a process to talk
to, and this module is that process: a small FastAPI app serving the static
page and a JSON view of the vaults. The same router is mounted under /ui on
the HTTP API server, for whoever already has one running.

The page can also be written out whole, `ctxvault ui --export memory.html`:
one file, scripts and fonts and data inlined, that opens without any server
and shows the memory as it was at that moment. Live or snapshot, the page is
the same; only where the data comes from changes.

This is the owner's view, like the CLI: it is not gated by agent names, and
restricted vaults are shown whole. So it is served only to the machine
running the server, unless `ctxvault ui --host` was given explicitly: on the
HTTP API server, which may listen beyond localhost for agents, a request from
elsewhere gets 403. Reading while another process writes is safe for SQLite,
which the episodic store opens in WAL mode; a semantic vault being indexed by
another process at the same moment may show a partial document list.
"""

import base64
import json
import mimetypes
import os
import subprocess
import sys
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ctxvault.core import vault_router
from ctxvault.core.exceptions import (DocumentNotFoundError, VaultNotFoundError, VaultPathMissingError,
                                      VaultTypeNotValidError)
from ctxvault.core.vaults.episodic import EpisodicVault
from ctxvault.core.vaults.semantic import SemanticVault
from ctxvault.core.vaults.skill import SkillVault
from ctxvault.utils import config as registry

STATIC = Path(__file__).parent / "static"
# How far back the overview counts changes, one bucket per day.
ACTIVITY_DAYS = 30

# --- who may read ---------------------------------------------------------------

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

def _is_local(request: Request) -> bool:
    return request.client is not None and request.client.host in _LOOPBACK

def _owner_only(request: Request) -> None:
    """The page shows every vault, restricted ones included, like the CLI
    does for whoever sits at the machine. So that is who gets it: a request
    from another host is refused, unless the server was started as
    `ctxvault ui` with a host chosen on purpose (see `create_app`)."""
    if getattr(request.app.state, "ui_serves_everyone", False) or _is_local(request):
        return
    raise HTTPException(
        status_code=403,
        detail="The memory viewer is served only to the machine running ctxvault. "
               "Run `ctxvault ui --host <interface>` to expose it on purpose.",
    )

router = APIRouter(prefix="/ui", tags=["UI"], dependencies=[Depends(_owner_only)])

# --- the JSON the page reads ------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _instant(value) -> datetime | None:
    """An ISO timestamp as an aware datetime. A naive one is read as UTC,
    which is how the episodic store reads what callers hand it."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t

def _disk_bytes(*paths) -> int:
    """What the vault occupies on disk: every file under its folder, plus its
    database when that lives elsewhere. Each file is counted once."""
    files = set()
    for path in filter(None, paths):
        path = Path(path)
        if path.is_file():
            files.add(path.resolve())
        elif path.is_dir():
            files.update(f.resolve() for f in path.rglob("*") if f.is_file())
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total

def _changes(vault) -> list[datetime]:
    """Every moment the vault changed, as far as its store remembers.

    Episodic: what the vault recorded as events (statements recorded, closed,
    confirmed, put in dispute). Semantic: documents indexed. Skill: skills
    written; a file keeps only its last modification, so earlier edits are gone.
    """
    if isinstance(vault, EpisodicVault):
        values = vault.changes()
    elif isinstance(vault, SkillVault):
        values = [s.last_modified for s in vault.list_skills()]
    else:
        values = [d.indexed_at for d in vault.list_documents()]
    return [t for value in values if (t := _instant(value))]

def _activity(moments: list[datetime], today: date) -> list[int]:
    """Changes per local day over the last ACTIVITY_DAYS days, oldest first."""
    start = today - timedelta(days=ACTIVITY_DAYS - 1)
    per_day = Counter(t.astimezone().date() for t in moments)
    return [per_day.get(start + timedelta(days=i), 0) for i in range(ACTIVITY_DAYS)]

def _problem(error: Exception) -> str:
    """The error in a few words, for the list of what needs attention."""
    if isinstance(error, VaultPathMissingError):
        return "folder missing"
    if isinstance(error, VaultTypeNotValidError):
        return "unknown type"
    if isinstance(error, PermissionError) or "unable to open database" in str(error):
        return "cannot read its files"
    if "not a database" in str(error) or "malformed" in str(error):
        return "storage corrupt"
    return "cannot be opened"

def _default_model() -> str:
    from ctxvault.core.embedding import DEFAULT_EMBEDDING_MODEL
    return DEFAULT_EMBEDDING_MODEL

def summarize(entry: dict, today: date | None = None) -> dict:
    """One vault as the overview shows it: identity, access, how much it holds,
    what it takes on disk and how it changed lately.

    A vault that cannot be opened is still listed, with the error in place of
    the counts: a broken vault is exactly what an overview must show.
    """
    today = today or datetime.now().astimezone().date()
    # a registration without a type is a semantic vault, as vault_router reads it
    vault_type = entry.get("type") or "semantic"
    summary = {
        "name": entry["name"],
        "type": vault_type,
        "scope": entry.get("scope"),
        "path": entry.get("vault_path"),
        "restricted": bool(entry.get("restricted")),
        "allowed_agents": entry.get("allowed_agents") or [],
        "embedding_model": entry.get("embedding_model") or (_default_model() if vault_type == "semantic" else None),
        "embedding_default": not entry.get("embedding_model"),
        "disk_bytes": _disk_bytes(entry.get("vault_path"), entry.get("db_path")),
    }
    try:
        vault = vault_router.open_vault(entry["name"])
        if isinstance(vault, EpisodicVault):
            summary["counts"] = {**vault.stats(), "entities": len(vault.list_entities(include_closed=True))}
        elif isinstance(vault, SkillVault):
            summary["counts"] = {"skills": len(vault.list_skills())}
        else:
            documents, status = vault.list_documents(), vault.status()
            summary["counts"] = {
                "documents": len(documents),
                "chunks": sum(d.chunks_count for d in documents),
                "out_of_sync": sum(1 for d in status.documents if d.state != "in_sync"),
                "unindexed": len(status.unindexed),
            }
        moments = _changes(vault)
        last = max(moments, default=None)
        summary["last_activity"] = last.isoformat() if last else None
        summary["activity"] = _activity(moments, today)
    except Exception as error:  # the overview survives one broken vault
        summary["error"] = f"{type(error).__name__}: {error}"
        summary["problem"] = _problem(error)
    return summary

def where() -> dict:
    """The registries being read: the project's .ctxvault, found by walking up
    from the working directory, and the global one. Shown on the page, so an
    empty overview says where it looked rather than that nothing exists."""
    local = registry.find_local_root()
    return {"cwd": str(Path.cwd()), "local": str(local) if local else None, "global": str(registry.GLOBAL_DIR)}

def overview() -> dict:
    today = datetime.now().astimezone().date()
    return {"generated_at": _now(), "today": today.isoformat(), "activity_days": ACTIVITY_DAYS,
            "registry": where(), "home": str(Path.home()), "vaults": [summarize(v, today) for v in registry.get_vaults()]}

def _open(name: str):
    try:
        return vault_router.open_vault(name)
    except VaultNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

def _skill(vault: SkillVault, info) -> dict:
    """A skill with what the library knows about it: the index entry, the
    file's stat, the instructions and the author's extra frontmatter."""
    return {**info.model_dump(), **vault.read_skill(info.skill_name).model_dump(mode="json")}

# --- semantic documents: their chunks -------------------------------------------

def document(vault: SemanticVault, doc_id: str) -> dict:
    """A document as the agent meets it: the reconstructed text the library
    gives, and its chunks in index order. The text repeats whatever the
    chunker carried over between chunks; the library says so in `warning`."""
    content = vault.get_document_content(doc_id=doc_id).model_dump()
    content["chunks"] = [{"index": i, "text": text, "words": len(text.split())}
                         for i, text in enumerate(vault.get_document_chunks(doc_id=doc_id))]
    return content

def _evidence(vault: EpisodicVault) -> tuple[dict, dict]:
    """Per episode, each time it was asserted again (when, by whom) and each
    dispute it is in (with which episode, noticed when, with what note)."""
    attestations: dict[str, list] = {}
    for row in vault.attestations():
        attestations.setdefault(row["episode_id"], []).append({"at": row["at"], "source": row["source"]})
    disputes: dict[str, list] = {}
    for row in vault.disputes():
        for one, other in ((row["episode_a"], row["episode_b"]), (row["episode_b"], row["episode_a"])):
            disputes.setdefault(one, []).append({"with": other, "noticed_at": row["noticed_at"], "note": row["note"]})
    return attestations, disputes

def vault_payload(name: str) -> dict:
    """Everything the vault page needs for one vault, by type."""
    vault = _open(name)
    payload = {"name": name, "type": vault.config.get("type", "semantic")}
    if isinstance(vault, EpisodicVault):
        # every episode goes to the page at once; filtering by time, entity
        # and metadata happens there, so the time cursor moves without a round trip
        attestations, disputes = _evidence(vault)
        payload["episodes"] = [{**e.model_dump(), "attestations": attestations.get(e.id, []), "disputes": disputes.get(e.id, [])}
                               for e in vault.all_episodes()]
        payload["entities"] = [e.model_dump() for e in vault.list_entities(include_closed=True)]
        payload["stats"] = vault.stats()
    elif isinstance(vault, SkillVault):
        payload["skills"] = [_skill(vault, info) for info in vault.list_skills()]
    else:
        status = vault.status()
        states = {s.doc_id: {"state": s.state, "modified_at": s.modified_at} for s in status.documents}
        payload["documents"] = [{**d.model_dump(), **states.get(d.doc_id, {})} for d in vault.list_documents()]
        payload["unindexed"] = status.unindexed
    return payload

@router.get("/api/overview")
def api_overview() -> dict:
    return overview()

@router.get("/api/vaults/{name}")
def api_vault(name: str) -> dict:
    return vault_payload(name)

@router.get("/api/vaults/{name}/documents/{doc_id}")
def api_document(name: str, doc_id: str) -> dict:
    vault = _open(name)
    if not isinstance(vault, SemanticVault):
        raise HTTPException(status_code=400, detail=f"Vault '{name}' holds no documents.")
    try:
        return document(vault, doc_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

@router.get("/api/vaults/{name}/search")
def api_search(name: str, q: str = Query(min_length=1), n: int = 5) -> dict:
    """A semantic query as the agent would run it, with the library's own
    scores. Live only."""
    vault = _open(name)
    if not isinstance(vault, SemanticVault):
        raise HTTPException(status_code=400, detail=f"Vault '{name}' is not searchable by meaning.")
    return vault.query(text=q, n_results=n).model_dump()

# A file manager is a program on the machine running this server, so the
# request must come from that same machine, whatever host the server listens
# on. Only a registered vault's own folder can be opened; nothing in the
# request names a path.

def _reveal(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a folder, opened in Explorer
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

@router.post("/api/vaults/{name}/reveal")
def api_reveal(name: str, request: Request) -> dict:
    """Open the vault's folder in the system file manager. Local requests only."""
    if not _is_local(request):
        raise HTTPException(status_code=403, detail="The folder can only be opened from the machine running ctxvault.")
    try:
        path = registry.get_vault_config(name).get("vault_path")
    except VaultNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    if not path or not Path(path).is_dir():
        raise HTTPException(status_code=404, detail=f"Vault '{name}' has no folder at {path}.")
    try:
        _reveal(path)
    except (OSError, AttributeError) as error:
        raise HTTPException(status_code=500, detail=f"Could not open a file manager: {error}")
    return {"opened": path}

# --- the page -----------------------------------------------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def page() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")

class UIStatic(StaticFiles):
    """The page's scripts and styles, revalidated on every load. Without this a
    browser keeps a heuristic copy (the files carry Last-Modified and no
    Cache-Control), and after an upgrade it runs the old app against the new
    server. The ETag still turns an unchanged file into a 304."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response

def create_app() -> FastAPI:
    """The standalone app behind `ctxvault ui`: the page, its assets, its JSON.

    Whoever starts it chooses the host, so it answers every request it gets:
    on the default 127.0.0.1 only the machine itself can connect, and another
    `--host` is a decision taken on purpose. The HTTP API server, which mounts
    the same router without this flag, serves the page to loopback only.
    """
    app = FastAPI(title="ctxvault ui", docs_url=None, redoc_url=None)
    app.state.ui_serves_everyone = True
    app.include_router(router)
    app.mount("/ui/static", UIStatic(directory=STATIC), name="ui-static")

    @app.get("/", include_in_schema=False)
    def root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/ui/")

    return app

def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    found = where()
    print(f"reading {found['local'] or 'no project .ctxvault from ' + found['cwd']} and {found['global']}")

    url = f"http://{host}:{port}/ui/"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")

# --- the snapshot -------------------------------------------------------------

def snapshot() -> dict:
    """Every vault with its full payload: what the exported page carries."""
    data = overview()
    for summary in data["vaults"]:
        if "error" not in summary:
            try:
                summary["payload"] = vault_payload(summary["name"])
                if summary["type"] == "semantic":
                    summary["payload"]["contents"] = _contents(summary["name"], summary["payload"]["documents"])
            except Exception as error:
                summary["error"] = f"{type(error).__name__}: {error}"
    return data

def _contents(name: str, documents: list[dict]) -> dict:
    """The reconstructed text of every document, by id: a snapshot has no
    server to ask when a document is opened."""
    vault = vault_router.open_vault(name)
    out = {}
    for entry in documents:
        try:
            out[entry["doc_id"]] = document(vault, entry["doc_id"])
        except Exception as error:
            out[entry["doc_id"]] = {"error": f"{type(error).__name__}: {error}"}
    return out

def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

def _inline_fonts(css: str) -> str:
    for font in sorted((STATIC / "fonts").glob("*.woff2")):
        css = css.replace(f"url('fonts/{font.name}')", f"url('{_data_uri(font)}')")
    return css

def export_html(data: dict | None = None, note: str | None = None) -> str:
    """The page as one self-contained file around a snapshot of the vaults.

    index.html is the template: its stylesheet and script tags are replaced
    by the files' contents, fonts become data URIs, and the snapshot is set
    on `window` before the app script runs, which is how the page knows it
    is looking at a moment rather than at a live server. The logos travel the
    same way, as data URIs on `window.CTXVAULT_ASSETS`. A `note` is shown at
    the top of the page until dismissed: what this snapshot is, for whoever
    opens it without knowing.
    """
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = "\n".join(line for line in html.splitlines() if 'rel="preload"' not in line)  # fonts are inlined below
    css = _inline_fonts((STATIC / "styles.css").read_text(encoding="utf-8"))
    html = html.replace('<link rel="stylesheet" href="static/styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace('href="static/favicon.png"', f'href="{_data_uri(STATIC / "favicon.png")}"')

    scripts = []
    for line in html.splitlines():
        if '<script src="static/' in line:
            name = line.split('src="static/')[1].split('"')[0]
            scripts.append((line.strip(), (STATIC / name).read_text(encoding="utf-8")))
    payload = json.dumps(data if data is not None else snapshot(), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # a "</script>" inside content must not close the tag
    assets = json.dumps({"logoDark": _data_uri(STATIC / "logo-dark.svg"), "logoLight": _data_uri(STATIC / "logo-light.svg")})
    bundle = f"<script>window.CTXVAULT_SNAPSHOT = {payload};\nwindow.CTXVAULT_ASSETS = {assets};"
    if note:
        bundle += f"\nwindow.CTXVAULT_NOTE = {json.dumps(note, ensure_ascii=False).replace('</', '<\\/')};"
    bundle += "</script>\n"
    bundle += "\n".join(f"<script>\n{source}\n</script>" for _, source in scripts)
    first = True
    for tag, _ in scripts:
        html = html.replace(tag, bundle if first else "", 1)
        first = False
    return html

def export(path: Path, data: dict | None = None, note: str | None = None) -> Path:
    path = Path(path)
    path.write_text(export_html(data, note), encoding="utf-8")
    return path
