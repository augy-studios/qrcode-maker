#!/usr/bin/env bash
#
# tmux wrapper. Keeps the bot in a detached session that survives your SSH
# connection dropping, which is the whole reason for running it this way.
#
#   ./run.sh start      start it detached
#   ./run.sh stop       stop it
#   ./run.sh restart    stop, then start
#   ./run.sh attach     open the live console, detach again with ctrl-b then d
#   ./run.sh status     is it running
#   ./run.sh logs       follow the log file
#   ./run.sh check      verify the environment without connecting
#
set -euo pipefail

SESSION="${QRBOT_SESSION:-uwuqr}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
PYTHON="$VENV/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "No virtual environment at $VENV" >&2
    echo "Create one with:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is not installed. Try:  sudo apt install tmux" >&2
    exit 1
fi

running() { tmux has-session -t "$SESSION" 2>/dev/null; }

case "${1:-start}" in
    start)
        if running; then
            echo "Already running in tmux session '$SESSION'."
            exit 0
        fi
        tmux new-session -d -s "$SESSION" -c "$DIR" "$PYTHON bot.py ${*:2}"
        sleep 1
        if running; then
            echo "Started in tmux session '$SESSION'."
            echo "Attach with:  ./run.sh attach"
        else
            echo "It exited immediately. Check data/bot.log." >&2
            exit 1
        fi
        ;;
    stop)
        if running; then
            tmux kill-session -t "$SESSION"
            echo "Stopped."
        else
            echo "It was not running."
        fi
        ;;
    restart)
        "$0" stop || true
        sleep 1
        "$0" start "${@:2}"
        ;;
    attach)
        running || { echo "It is not running." >&2; exit 1; }
        tmux attach -t "$SESSION"
        ;;
    status)
        if running; then
            echo "Running in tmux session '$SESSION'."
            tmux list-panes -t "$SESSION" -F '  pane #{pane_index}, pid #{pane_pid}, #{pane_current_command}'
        else
            echo "Not running."
            exit 1
        fi
        ;;
    logs)
        exec tail -n 100 -f "$DIR/data/bot.log"
        ;;
    check)
        exec "$PYTHON" bot.py --check
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|attach|status|logs|check}" >&2
        exit 2
        ;;
esac
