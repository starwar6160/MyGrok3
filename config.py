"""
Configuration for MyGrok3

This file centralizes all configurable parameters for the application.
"""

# --- Model Configuration ---
# The default model to use for new conversations.
DEFAULT_MODEL = "google/gemini-flash-1.5-8b"

# The model to use for generating conversation titles.
TITLE_MODEL = "google/gemini-flash-1.5-8b"


# --- Session Management Configuration ---

# --- Conversation Cleanup Configuration ---

# The maximum age (in hours) of a conversation before it's considered for cleanup.
# Conversations older than this will be deleted if they have too few messages.
CLEANUP_MAX_AGE_HOURS = 1

# The minimum number of messages a conversation must have to be kept,
# even if it is older than CLEANUP_MAX_AGE_HOURS.
CLEANUP_MIN_MESSAGES = 5
