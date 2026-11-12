"""
Can this LLM replace a human annotator here? The alt-test, on a live study.

Runs :func:`potato.server_utils.alt_test.alt_test` (Calderon, Reichart & Dror,
ACL 2025) between one declared machine annotator (``machine_annotators``,
see ``potato/annotator_origin.py``) and the study's human annotators, on one
scheme. Labels are gathered the way ``/admin/iaa`` gathers them, so the two
pages never disagree about what an annotator answered.

The test needs several people on the same items: by default at least three
human annotators with 30 or more items each that the machine also labelled.
Below that the report says what is missing rather than giving a number. A Solo
Mode study has one human and so cannot run it; its blind-agreement card is the
measure there.
"""

from typing import Any, Dict, Optional

#: Scheme types the test can score, and the alignment metric for each.
METRIC_FOR_TYPE = {
    'radio': 'accuracy', 'select': 'accuracy', 'multirate': None,
    'likert': 'neg_rmse', 'slider': 'neg_rmse', 'number': 'neg_rmse',
}


def build_report(item_state_manager, user_state_manager, config: Dict[str, Any],
                 annotator: str, schema_name: str, epsilon: float = 0.2,
                 metric: Optional[str] = None) -> Dict[str, Any]:
    """The alt-test of ``annotator`` against the humans on ``schema_name``.

    Raises:
        ValueError: unknown scheme or annotator, an annotator who is not a
            declared machine, or a scheme type the test cannot score.
    """
    from potato.annotator_origin import is_human, origin_of
    from potato.server_utils.alt_test import alt_test
    from potato.server_utils.iaa.dispatcher import _gather_labels

    schemes = config.get('annotation_schemes') or []
    scheme = next((s for s in schemes if s.get('name') == schema_name), None)
    if scheme is None:
        raise ValueError(f"No annotation scheme named {schema_name!r}")
    atype = scheme.get('annotation_type')
    metric = metric or METRIC_FOR_TYPE.get(atype)
    if metric is None:
        raise ValueError(
            f"The alt-test scores single-answer schemes "
            f"({', '.join(t for t, m in METRIC_FOR_TYPE.items() if m)}); "
            f"{schema_name!r} is {atype!r}")

    user_states = {u: user_state_manager.get_user_state(u)
                   for u in user_state_manager.get_user_ids()}
    user_states = {u: s for u, s in user_states.items() if s is not None}
    machine_state = user_states.get(annotator)
    if machine_state is None:
        raise ValueError(f"No annotator {annotator!r}")
    if is_human(machine_state):
        raise ValueError(
            f"{annotator!r} is not a declared machine annotator. The alt-test "
            f"asks whether a machine can stand in for a person, so the "
            f"annotator under test is declared under machine_annotators.")

    humans_states = {u: s for u, s in user_states.items() if is_human(s)}
    numeric = metric == 'neg_rmse'
    items = [iid for iid, who in item_state_manager.instance_annotators.items()
             if annotator in who]
    rows = _gather_labels(items, {**humans_states, annotator: machine_state},
                          schema_name, numeric=numeric, scheme=scheme)

    llm, humans = {}, {}
    for iid, per_user in rows.items():
        if annotator not in per_user:
            continue
        llm[iid] = per_user[annotator][0]
        for uid, values in per_user.items():
            if uid != annotator:
                humans.setdefault(uid, {})[iid] = values[0]

    result = alt_test(llm, humans, epsilon=epsilon, metric=metric).to_dict()
    result.update({
        'schema': schema_name,
        'annotation_type': atype,
        'annotator': annotator,
        'annotator_origin': origin_of(machine_state),
        'metric': metric,
        'n_items_machine_labelled': len(items),
    })
    return result


def declared_machines(user_state_manager) -> Dict[str, Any]:
    """Machine annotators present in the study, with their origin records."""
    from potato.annotator_origin import is_machine, origin_of
    out = {}
    for uid in user_state_manager.get_user_ids():
        state = user_state_manager.get_user_state(uid)
        if state is not None and is_machine(state):
            out[uid] = origin_of(state)
    return out
