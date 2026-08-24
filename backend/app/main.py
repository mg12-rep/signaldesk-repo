import logging
import sys

from app.api.router import api_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SignalDesk API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount master API router
app.include_router(api_router)


@app.get("/")
def root():
    return {"status": "online", "system": "SignalDesk Engine"}


# Force standard output streaming for all app logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

logger = logging.getLogger("signaldesk")
logger.info("Starting SignalDesk API engine...")
