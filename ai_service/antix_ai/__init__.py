"""Antix News AI service."""

import asyncio
import sys

if sys.platform == "win32":  # psycopg async cannot run on the default Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
