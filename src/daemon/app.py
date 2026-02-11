"""FastAPI app stub. Daemon logic (e.g. watch Vivaldi) TBD."""
from fastapi import FastAPI

app = FastAPI(title="Lilith Browser", description="Browser history/bookmarks daemon stub")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
