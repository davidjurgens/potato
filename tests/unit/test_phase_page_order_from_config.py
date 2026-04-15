from potato.phase import UserPhase
from potato.user_state_management import UserStateManager


def test_phase_pages_follow_config_order_even_if_registered_in_reverse():
    config = {
        "output_annotation_dir": ".",
        "phases": {
            "order": ["prestudy_intro", "prestudy_questions", "annotation"],
            "prestudy_intro": {"type": "prestudy", "file": "intro.json"},
            "prestudy_questions": {"type": "prestudy", "file": "questions.json"},
            "annotation": {"type": "annotation"},
        },
    }

    usm = UserStateManager(config)

    # Simulate pages being registered in the wrong order by a loader path.
    usm.add_phase(UserPhase.PRESTUDY, "prestudy_questions", "questions.html")
    usm.add_phase(UserPhase.PRESTUDY, "prestudy_intro", "intro.html")

    assert usm._get_phase_pages(UserPhase.PRESTUDY) == (
        "prestudy_intro",
        "prestudy_questions",
    )
