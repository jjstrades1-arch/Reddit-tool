"""Shared core: config, database, API clients, scheduling and compliance.

Tool modules import from ``core`` only -- never from each other -- which keeps
the suite a single cohesive application rather than a pile of scripts.
"""
