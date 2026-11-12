"""The agent select offers every agent the widget itself names.

`agents:` REPLACED the observed roster. `failure_attribution` builds its step
select from the data and labels each step with its agent, so on a trace where
the reviewer raises the error the step select read

    7. [reviewer] Two agents wrote auth.py in the same second.

while the agent select offered planter/researcher/coder/auditor -- `auditor`
being a name that appears only in the config, `reviewer` only in the data. The
widget showed the annotator that the reviewer exists, named them on the step
they were being asked about, and then refused to let them be selected. The
saved record read

    {"responsible_agent":"coder","decisive_step":6,"reason":""}

which is a coherent-looking record of an incoherent judgment, exported as-is,
with no way for the annotator to record the true one.

Six agent-evaluation schemes split on this: four derive the roster from the
data, two took it from the config. Both of the two are fixed here, and they had
their own copies of the rule -- which is why they could disagree at all.

A configured roster is still honoured: it keeps its order and it comes first,
because "score this fixed team regardless of who turned up" is a real thing to
want. What is not defensible is dropping someone the same widget just named.
"""

import json
import re
import shutil
import subprocess
import tempfile

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to run the widget JS")


TRACE = [
    {"agent": "planner", "text": "Plan the fix."},
    {"agent": "coder", "text": "Write auth.py."},
    {"agent": "researcher", "text": "Also write auth.py."},
    {"agent": "reviewer", "text": "Two agents wrote auth.py in the same second."},
]


def _script(annotation_type, scheme_extra):
    from potato.server_utils.schemas.registry import schema_registry

    scheme = {"annotation_type": annotation_type, "name": "attribution",
              "description": "Who is responsible?", "steps_key": "steps",
              "agent_key": "agent"}
    scheme.update(scheme_extra)
    html, _ = schema_registry.generate(scheme)
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert scripts, "the generator emitted no script"
    return max(scripts, key=len)


def _unique_agents(annotation_type, scheme_extra):
    """Run the generated widget's own roster function against the trace."""
    script = _script(annotation_type, scheme_extra)
    harness = """
global.window = global;
var warnings = [];
global.console = { warn: function (m) { warnings.push(m); }, log: function () {},
                   error: function () {} };
function stubEl() {
  return { style: {}, dataset: {}, innerHTML: '', value: '',
           querySelector: function () { return stubEl(); },
           querySelectorAll: function () { return []; },
           addEventListener: function () {}, appendChild: function () {},
           getAttribute: function () { return null; },
           setAttribute: function () {} };
}
var record = { getAttribute: function () { return %s; } };
global.document = {
  getElementById: function (id) {
    return id === 'instance_data' ? { textContent: %s } : stubEl();
  },
  querySelector: function (sel) {
    return sel === '[data-instance-json]' ? record : stubEl();
  },
  querySelectorAll: function () { return []; },
  addEventListener: function () {}, createElement: function () { return stubEl(); },
  readyState: 'complete'
};
%s
var roster = (typeof uniqueAgents === 'function')
  ? (uniqueAgents.length ? uniqueAgents(%s) : uniqueAgents())
  : null;
process.stdout.write(JSON.stringify({roster: roster, warnings: warnings}));
""" % (json.dumps(json.dumps({"steps": TRACE})),
       json.dumps(json.dumps({"steps": TRACE})),
       script.replace("(function()", "(function _iife()", 1),
       json.dumps(TRACE))

    # The widget wraps itself in an IIFE, so `uniqueAgents` is not visible from
    # outside it. Slice the function out and run it against the same stubs
    # rather than re-implementing the rule in the test.
    match = re.search(r"function uniqueAgents\([^)]*\)\s*\{", script)
    assert match, "the roster function was renamed; this test is measuring nothing"
    start = match.start()
    depth, i = 0, script.index("{", start)
    while True:
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = script[start:i + 1]
    agent_of = re.search(r"function agentOf\([^)]*\)\s*\{.*?\n        \}", script, re.S)
    assert agent_of, "agentOf was renamed"

    runner = """
var SCHEMA = 'attribution';
var CONFIG = %s;
var warnings = [];
var console = { warn: function (m) { warnings.push(m); } };
function instanceData() { return %s; }
%s
%s
var roster = uniqueAgents.length ? uniqueAgents(%s) : uniqueAgents();
process.stdout.write(JSON.stringify({roster: roster, warnings: warnings}));
""" % (json.dumps({"steps_key": "steps", "agent_key": "agent",
                   "agents": scheme_extra.get("agents", [])}),
       json.dumps({"steps": TRACE}),
       agent_of.group(0), body, json.dumps(TRACE))

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(runner)
        path = fh.name
    result = subprocess.run(["node", path], capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stderr[:1500]
    return json.loads(result.stdout)


class TestFailureAttribution:

    def test_a_data_only_agent_can_be_selected(self):
        out = _unique_agents("failure_attribution",
                             {"agents": ["planner", "researcher", "coder",
                                         "auditor"]})
        assert "reviewer" in out["roster"], (
            "the step select names [reviewer] on the step the annotator is "
            "judging, and the agent select would not offer them")

    def test_the_configured_roster_keeps_its_order_and_comes_first(self):
        configured = ["planner", "researcher", "coder", "auditor"]
        out = _unique_agents("failure_attribution", {"agents": configured})
        assert out["roster"][:4] == configured

    def test_a_config_only_agent_is_still_offered(self):
        """`agents:` as a deliberate roster is a real thing to want."""
        out = _unique_agents("failure_attribution", {"agents": ["auditor"]})
        assert "auditor" in out["roster"]

    def test_the_discrepancy_is_reported(self):
        out = _unique_agents("failure_attribution",
                             {"agents": ["planner", "auditor"]})
        joined = " ".join(out["warnings"])
        assert "reviewer" in joined, "an agent added from the data is not named"
        assert "auditor" in joined, "an agent who never acts is not named"

    def test_no_config_means_the_observed_roster(self):
        out = _unique_agents("failure_attribution", {})
        assert out["roster"] == ["planner", "coder", "researcher", "reviewer"]
        assert out["warnings"] == []

    def test_a_matching_roster_says_nothing(self):
        out = _unique_agents("failure_attribution",
                             {"agents": ["planner", "coder", "researcher",
                                         "reviewer"]})
        assert out["warnings"] == []
        assert out["roster"] == ["planner", "coder", "researcher", "reviewer"]


class TestAgentScorecard:
    """The other of the two schemes that took the roster from the config. Its
    version of the bug: the reviewer who acted four times and raised the error
    got no row, and the auditor who never appeared got a full scorecard to
    fill in."""

    def test_a_data_only_agent_gets_a_row(self):
        out = _unique_agents("agent_scorecard",
                             {"agents": ["planner", "coder"],
                              "dimensions": ["accuracy"]})
        assert "reviewer" in out["roster"]

    def test_a_config_only_agent_keeps_its_row(self):
        out = _unique_agents("agent_scorecard",
                             {"agents": ["auditor"], "dimensions": ["accuracy"]})
        assert "auditor" in out["roster"]

    def test_the_two_schemes_now_agree(self):
        """They had their own copies of the rule, which is how they came to
        disagree with the other four schemes and with each other."""
        roster_a = _unique_agents(
            "failure_attribution", {"agents": ["planner"]})["roster"]
        roster_b = _unique_agents(
            "agent_scorecard",
            {"agents": ["planner"], "dimensions": ["accuracy"]})["roster"]
        assert roster_a == roster_b
