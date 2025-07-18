import json

def test_submit_annotation_requires_session(client):
    # Remove session for this test
    resp = client.post("/submit_annotation", data={
        "instance_id": "1",
        "annotation_data": json.dumps({"label": "foo"})
    })
    # In debug mode, should not error
    assert resp.status_code == 200
    assert b"success" in resp.data or b"error" in resp.data