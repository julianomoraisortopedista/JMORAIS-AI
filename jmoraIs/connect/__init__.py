"""Scientific service connector interfaces."""

from .base import BaseConnector
from .pubmed import PubMedConnector

__all__ = ["BaseConnector", "PubMedConnector"]
