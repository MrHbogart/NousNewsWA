from __future__ import annotations

from .base import AgentServiceCore
from .budget import BudgetMixin
from .cards import CardsMixin
from .content import ContentMixin
from .fetching import FetchingMixin
from .scoring import ScoringMixin


class AgentService(FetchingMixin, CardsMixin, ContentMixin, ScoringMixin, BudgetMixin, AgentServiceCore):
    """The crawl -> score -> compose -> publish pipeline for one agent run.

    Behavior lives in the mixins above (see base.py's AgentServiceCore
    docstring); this class just assembles them. Every method this class
    exposes existed on the single AgentService class before the
    agent/services.py -> agent/services/ split.
    """
