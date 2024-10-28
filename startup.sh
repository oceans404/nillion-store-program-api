#!/bin/bash
export PATH="$HOME/.nilup/bin:$PATH"
exec python -m uvicorn main:app --host 0.0.0.0 --port $PORT