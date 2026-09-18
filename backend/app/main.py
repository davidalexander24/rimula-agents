"""Entry point uvicorn: `backend.app.main:app`. Dijalankan lewat `bash scripts/dev_up.sh <nama>`. Pemilik: David (B)."""

from .factory import create_app

app = create_app()
