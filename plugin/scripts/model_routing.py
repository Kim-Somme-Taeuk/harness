"""Stateless Codex spawn decisions; admission and native execution stay with the coordinator."""
import json
import sys

SOL = "gpt-6.1-sol"
ASTRA = "gpt-6-astra"


def route(request):
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    allowed = {"impact", "recovery", "failed_attempts", "available_models"}
    if request.keys() - allowed:
        raise ValueError("unknown routing field")
    impact = request.get("impact", "unknown")
    recovery = request.get("recovery", "unknown")
    if impact not in ("local", "component", "critical", "unknown"):
        raise ValueError("invalid impact")
    if recovery not in ("easy", "costly", "irreversible", "unknown"):
        raise ValueError("invalid recovery")
    failures = request.get("failed_attempts", 0)
    if type(failures) is not int or failures < 0:
        raise ValueError("failed_attempts must be a nonnegative integer")
    models = request.get("available_models")
    if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
        raise ValueError("available_models must list the current host model IDs")
    cost = ("high" if impact in ("critical", "unknown") or recovery in ("irreversible", "unknown")
            else "medium" if impact == "component" or recovery == "costly" else "low")
    if failures >= 3:
        return {"failure_cost": cost, "action": "stop", "reason": "three-attempt limit"}
    model = ASTRA if cost == "high" or failures else SOL
    if model not in models:
        return {"failure_cost": cost, "action": "blocked", "reason": f"model unavailable: {model}"}
    return {"failure_cost": cost, "action": "spawn", "escalated": bool(failures),
            "spawn_args": {"model": model, "fork_turns": "none"}}


def main():
    try:
        result = route(json.load(sys.stdin))
    except (ValueError, TypeError) as exc:
        print(json.dumps({"action": "blocked", "reason": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result["action"] == "spawn" else 1


if __name__ == "__main__":
    sys.exit(main())
