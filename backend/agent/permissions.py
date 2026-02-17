from __future__ import annotations

from rest_framework.permissions import BasePermission

from agent.control_auth import decode_control_token, extract_control_token


class HasAgentControlToken(BasePermission):
    message = "Valid control token required."

    def has_permission(self, request, view):
        token = extract_control_token(request)
        if not token:
            return False
        payload = decode_control_token(token)
        if not payload:
            return False
        request.agent_control_claims = payload
        return True
