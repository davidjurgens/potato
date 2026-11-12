import json

def test_submit_annotation_requires_session(client):
    """A save with no session is refused, and says so in the status line.

    This asserted 200 — which is what the route used to answer for every
    refusal, and the reason a discarded save was indistinguishable from a
    stored one: the page checks `response.ok` before it reads the body.
    """
    resp = client.post("/submit_annotation", data={
        "instance_id": "1",
        "annotation_data": json.dumps({"label": "foo"})
    })
    assert resp.status_code == 401
    assert b"error" in resp.data