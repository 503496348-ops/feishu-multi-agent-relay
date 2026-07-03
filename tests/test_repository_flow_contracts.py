import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from repository_flow_contracts import AgentSpec, FlowAction, validate_flow


def test_flow_action_renders_declared_context():
    action = FlowAction("triage", "reviewer", "repo=$repo issue=$issue")
    assert action.render({"repo": "alpha", "issue": 7}) == "repo=alpha issue=7"


def test_flow_validation_catches_unknown_agent_and_approval_contract():
    errors = validate_flow([AgentSpec("builder", "implementation")], [
        FlowAction("ship", "ghost", "repo=$repo"),
        FlowAction("danger", "builder", "repo=$repo", requires_approval=True),
    ])
    assert len(errors) == 2
    assert "unknown agent" in errors[0]
