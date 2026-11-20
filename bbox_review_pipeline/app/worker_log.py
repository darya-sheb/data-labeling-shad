"""Structured operational events shared by the API and the polling worker."""

import logging


def event(name, *, level=logging.INFO, **fields):
    logging.getLogger("butterfly.worker").log(level, name, extra={"fields": fields})
