#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

case "$1" in
    install)
        uv sync --dev
        ;;

    reset)
        rm -rf .venv
        uv sync --dev
        ;;

    run)
        uv run python -m router
        ;;

    check)
        uv run basedpyright src
        ;;

    test)
        uv run pytest
        ;;

    lock)
        uv lock
        ;;

    update)
        uv lock --upgrade
        ;;

    *)
        echo "Usage: ./src/run.sh {install|reset|run|check|test|lock|update}"
        exit 1
        ;;
esac