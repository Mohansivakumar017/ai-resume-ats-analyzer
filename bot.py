#!/usr/bin/env python3
"""
Entrypoint for Resume ATS Analyzer Telegram Bot.
Usage:
    python bot.py
"""
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.bot import main

if __name__ == "__main__":
    main()