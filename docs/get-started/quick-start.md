# Quick start

```bash
pip install ctxvault
```

--8<-- "README.md:quickstart"

## Install from source

With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
uv sync            # creates .venv and installs all dependencies
uv run ctxvault    # run the CLI
```

With pip:

```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```
