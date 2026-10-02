import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  (registers tables on Base)
from app.database import Base, engine
from app.logging_config import setup_logging
from app.routers import auth, bookings, centres, payments


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # no migrations in this project, tables are created on startup
    Base.metadata.create_all(bind=engine)
    logging.getLogger(__name__).info("app started")
    yield


app = FastAPI(
    title="EVE Diagnostics API",
    description="Diagnostic test bookings with simulated payments",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(centres.router)
app.include_router(bookings.router)
app.include_router(payments.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
