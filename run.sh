#!/usr/bin/env bash
# ==============================================================================
# Auto-Browser Execution Wrapper
# Automatically activates virtual environment and executes main.py
# ==============================================================================

set -e
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment if present
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
fi

# Execute main.py with all passed arguments
exec python "$PROJECT_ROOT/main.py" "$@"
