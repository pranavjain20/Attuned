#!/bin/bash
# Attuned daily playlist generation
# Syncs today's WHOOP data, then generates and pushes playlist to Spotify

cd /Users/pranavjain/Desktop/attuned
PYTHON=/Users/pranavjain/Desktop/supertrainer/backend/.venv/bin/python

echo "$(date): Starting daily playlist generation"

# Default profile (Pranav's existing DB)
echo "--- Profile: default ---"
$PYTHON main.py sync-whoop && $PYTHON main.py generate

# Named profiles
for profile in sister; do
    echo "--- Profile: $profile ---"
    $PYTHON main.py --profile $profile sync-whoop && $PYTHON main.py --profile $profile generate
done

echo "$(date): Done"
