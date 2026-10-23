"""Starts the agent service: python -m agent"""

import os

import uvicorn

uvicorn.run("agent.app:app", host="127.0.0.1", port=int(os.environ.get("AGENT_PORT", "8000")))
