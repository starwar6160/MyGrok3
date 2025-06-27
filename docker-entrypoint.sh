#!/bin/bash

set -e

if [ "$FLASK_ENV" = "development" ]; then
    flask run --host=0.0.0.0 --port=5000
else
    gunicorn -w 2 -b 0.0.0.0:5000 grok3:app
fi
