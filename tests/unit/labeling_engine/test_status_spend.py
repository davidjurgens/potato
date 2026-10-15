"""The human-label spend `status` reports is the one the cap is charged with.

Found by potato-skill (M3): status, and through it the admin page, summed
requests of every status, so after a re-certification cancelled 49 verify
requests the admin page said 406 where the budget table and the certificate
said 357. Organic labels were counted too.
"""

from potato.labeling_engine.items import ItemView
from potato.labeling_engine.model.records import HumanRequest
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache


def test_cancelled_and_organic_requests_are_not_spend(tmp_path):
    clear_db_cache()
    eng = Engine({"task_dir": str(tmp_path), "annotation_task_name": "m3",
                  "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                          "labels": ["a", "b"]}],
                  "labeling_engine": {"enabled": True,
                                      "sources": [{"id": "fx", "kind": "fixture"}],
                                      "budgets": {"human_labels": 100}}})
    eng.register_items([ItemView(f"i{k}", "t") for k in range(10)])
    eng.store.add_requests([HumanRequest(item_id=f"i{k}", schema="s", purpose="verify",
                                         inclusion_prob=None)
                            for k in range(6)])
    for r in eng.store.requests(status=["open"])[:2]:
        eng.store.update_request(r.id, status="cancelled")
    eng.record_human_label("i9", "s", "a", "u1")          # nobody asked: organic
    opened = eng.store.count_opened_requests()
    assert opened == 4
    assert eng.status()["budgets"]["human_labels"]["spent"] == opened
    clear_db_cache()
