"""Scientific service connector interfaces."""

from .base import BaseConnector
from .crossref import CrossrefConnector
from .pubmed import PubMedConnector

__all__ = ["BaseConnector", "CrossrefConnector", "PubMedConnector"]
