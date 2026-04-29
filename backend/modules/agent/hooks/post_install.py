"""
Agent post-install hook.
Runs after migration — no system config needed (agent is pure WS outbound).
"""
import logging

logger = logging.getLogger(__name__)


def run():
    logger.info("Hub Agent post-install: module ready (no system config required)")
    return True
