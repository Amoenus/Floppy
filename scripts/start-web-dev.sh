#!/usr/bin/env bash
set -e

# Floppy Web Distrobox Development Environment Starter
echo "Starting Floppy Web development environment..."

# Start Redis on isolated port (6380) in the background
echo "Starting Redis on port 6380..."
redis-server --port 6380 --daemonize yes --save "" --appendonly no

# Source the web-dev environment variables
if [ -f "../.env.web-dev" ]; then
    export $(cat ../.env.web-dev | xargs)
fi

# We assume this script is run from the `scripts/` directory or project root
cd "$(dirname "$0")/../src" || exit 1

# Ensure the virtual environment is activated if it exists, otherwise just use system python
if [ -d "../.venv" ]; then
    source ../.venv/bin/activate
fi

# Start Celery in the background
echo "Starting Celery workers..."
celery -A config worker --queues interactive --hostname celery-interactive@%h --loglevel INFO &
CELERY_PID1=$!
celery -A config worker --queues celery --beat --scheduler django --hostname celery@%h --loglevel INFO &
CELERY_PID2=$!

# Start Tailwind in the background
echo "Starting Tailwind watcher..."
npx @tailwindcss/cli -i ./static/css/input.css -o ./static/css/main.css --watch &
TAILWIND_PID=$!

echo "Starting Django Development Server on port 8080..."
python manage.py runserver 8080

# When Django is stopped, kill the background processes
echo "Shutting down..."
kill $CELERY_PID1 $CELERY_PID2 $TAILWIND_PID
redis-cli -p 6380 shutdown
