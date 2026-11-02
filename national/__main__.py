"""Starts the simulated national record service: python -m national"""

import os

import uvicorn

uvicorn.run("national.app:app", host="127.0.0.1", port=int(os.environ.get("NATIONAL_PORT", "8090")))
