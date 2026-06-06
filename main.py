#!/usr/bin/env python3
"""GRASS - Graph Retrieval-based Agentic Supply Chain System

Main entry point for running the FastAPI server.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["src", "config"],
        reload_excludes=["data/*", "*.pyc", "__pycache__"],
        log_level="info",
    )
