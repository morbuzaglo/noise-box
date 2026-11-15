"""Start the local API on 127.0.0.1 only."""
import pathlib
import sys

import uvicorn

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, log_level="info")
