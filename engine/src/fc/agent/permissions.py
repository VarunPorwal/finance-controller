"""Roles and permissions — PRD §9.2.

§9.2 says enforcement happens at three points: the FastAPI dependency, the RLS
policy, and the command validator, "so that an instruction cannot do what a
click cannot". This module is the third one, and it is deliberately the same
table the other two would consult rather than a parallel set of rules — an
instruction layer with its own, more permissive, notion of who may do what is
a privilege-escalation route dressed as a convenience.
"""

from __future__ import annotations

__all__ = ["PERMISSIONS", "ROLES", "VERB_ACTIONS", "can", "roles_permitting"]

#: §9.2, verbatim. ``*`` is a wildcard on either half of ``resource:verb``.
PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset({"*"}),
    "finance_manager": frozenset(
        {"run:*", "exception:*", "rule:*", "cluster:*", "agent:*", "audit:read"}
    ),
    "finance_exec": frozenset(
        {
            "run:create",
            "run:read",
            "exception:*",
            "rule:draft",
            "rule:read",
            "cluster:*",
            "agent:*",
            "audit:read",
        }
    ),
    "auditor": frozenset({"*:read", "audit:*"}),
    "viewer": frozenset({"run:read", "summary:read"}),
}

#: Most-privileged first. Used to name the role a refusal would need (§8.5).
ROLES: tuple[str, ...] = ("owner", "finance_manager", "finance_exec", "auditor", "viewer")

#: What each command verb actually asks permission to do.
#:
#: ``create_rule`` maps to ``rule:draft``, not ``rule:create``: a rule born from
#: an instruction is a *draft*, and it still has to be back-tested and activated
#: through the rulebook by somebody holding ``rule:*``. That is why
#: ``finance_exec`` can propose one and cannot switch it on.
VERB_ACTIONS: dict[str, str] = {
    "resolve": "exception:resolve",
    "write_off": "exception:write_off",
    "link_to": "exception:link",
    "post_entries": "exception:post_entries",
    "escalate": "exception:escalate",
    "snooze": "exception:snooze",
    "reclassify": "exception:reclassify",
    "create_rule": "rule:draft",
    "split_cluster": "cluster:split",
    "merge_cluster": "cluster:merge",
    "rerun": "run:create",
    "notify": "agent:notify",
    "query": "agent:read",
    "explain": "agent:read",
}


def can(role: str, action: str) -> bool:
    """Does ``role`` hold ``action``, written ``resource:verb``?"""
    perms = PERMISSIONS.get(role)
    if perms is None:
        return False
    if "*" in perms:
        return True
    resource, _, verb = action.partition(":")
    return action in perms or f"{resource}:*" in perms or f"*:{verb}" in perms


def roles_permitting(action: str) -> tuple[str, ...]:
    """Every role that holds ``action``, most-privileged first.

    §8.5 requires a refusal to *name the required role* rather than just say no,
    so the person reading it knows who to ask.
    """
    return tuple(role for role in ROLES if can(role, action))
