#!/bin/bash
# Railway deploy protocol wrapper for Claude (CB404 discord bot).
# Delegates to the global deploy script.
exec bash ~/.claude/scripts/railway-deploy.sh "$@"
