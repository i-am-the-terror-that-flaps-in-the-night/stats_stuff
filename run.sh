#!/bin/bash
source .venv/bin/activate
uvicorn main:app --reload \
  --reload-exclude "__pycache__" \
  --reload-exclude ".git" \
  --reload-exclude ".pytest_cache" \
  --reload-exclude ".ruff_cache" \
  --reload-exclude "Data" \
  --reload-exclude ".venv"
