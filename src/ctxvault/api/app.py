from fastapi import FastAPI
from ctxvault.api.routes import ctxvault_router
from ctxvault.ui import server as ui

app = FastAPI()

app.include_router(ctxvault_router)
# The read-only memory view, at /ui, for whoever already runs the API server.
app.include_router(ui.router)
app.mount("/ui/static", ui.UIStatic(directory=ui.STATIC), name="ui-static")

@app.get("/")
def root():
    return {"message": "Welcome to CtxVault!"}