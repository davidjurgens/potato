"""Held-out metrics for transcripts and diarization.

Standard library only, like the rest of ``evaluation``.

- transcript: word error rate and character error rate against the
  annotators' corrections, pooled over turns (errors over reference length),
  and the same WER for the ASR text the item came with, so a run shows what
  it gained. The headline is ``word_accuracy``, max(0, 1 - WER): headlines
  are compared higher-is-better.
- segments: diarization error rate, missed speech plus false alarm plus
  speaker confusion over the reference speech, on a 10 ms grid, with each
  predicted speaker mapped to the reference speaker it overlaps most in the
  best one-to-one assignment. No collar; overlapping speech counts once per
  speaker.

Spectrogram boxes are scored as image boxes on the rendered spectrogram, by
``evaluation`` like any detection.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

__all__ = ["edit_distance", "score_transcripts", "diarization_error",
           "score_diarization", "STEP_S"]

#: Diarization grid, seconds.
STEP_S = 0.01


def edit_distance(a: Sequence[Any], b: Sequence[Any]) -> int:
    """Levenshtein distance between two sequences."""
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def _words(text: str) -> List[str]:
    """Lower case, punctuation off, so "Hello," and "hello" are one word."""
    return re.sub(r"[^\w\s']", " ", str(text or "").lower()).split()


def _chars(text: str) -> List[str]:
    return list(" ".join(_words(text)))


def _transcript_texts(payload: Any) -> Dict[int, str]:
    """``{turn index: text}`` from a prediction: the speech_transcript answer
    shape (``correction``) or plain ``text``."""
    entries = payload if isinstance(payload, list) else (
        payload.get("turns") if isinstance(payload, dict) else None) or []
    out = {}
    for entry in entries:
        if isinstance(entry, dict):
            try:
                out[int(entry.get("index"))] = str(entry.get("correction", entry.get("text")) or "")
            except (TypeError, ValueError):
                continue
    return out


def score_transcripts(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """WER and CER over the corrected turns. A turn the model gave no text
    for scores as the ASR's text: a model that left a turn alone kept what
    was there."""
    word_errors = word_total = char_errors = char_total = asr_errors = 0
    for target, payload in zip(gold, predicted):
        guesses = _transcript_texts(payload)
        for turn in target or []:
            reference = _words(turn["text"])
            guess = guesses.get(int(turn["index"]), turn.get("asr_text", ""))
            word_errors += edit_distance(reference, _words(guess))
            word_total += len(reference)
            char_errors += edit_distance(_chars(turn["text"]), _chars(guess))
            char_total += len(_chars(turn["text"]))
            asr_errors += edit_distance(reference, _words(turn.get("asr_text", "")))
    if not word_total:
        return {}
    wer = word_errors / word_total
    return {"wer": wer, "cer": char_errors / char_total if char_total else 0.0,
            "wer_asr": asr_errors / word_total, "word_accuracy": max(0.0, 1.0 - wer),
            "n_words": float(word_total)}


def _speaker_frames(turns: Sequence[Dict[str, Any]]) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for turn in turns or []:
        try:
            start, end = float(turn["start"]), float(turn["end"])
        except (KeyError, TypeError, ValueError):
            continue
        speaker = str(turn.get("speaker", turn.get("label", "")))
        frames = out.setdefault(speaker, set())
        frames.update(range(int(round(start / STEP_S)), int(round(end / STEP_S))))
    return out


def diarization_error(reference: Sequence[Dict[str, Any]],
                      hypothesis: Sequence[Dict[str, Any]]) -> Tuple[float, Dict[str, float]]:
    """``(DER, components in seconds)`` for one recording."""
    from potato.training.structured_metrics import hungarian
    ref = _speaker_frames(reference)
    hyp = _speaker_frames(hypothesis)
    ref_names, hyp_names = sorted(ref), sorted(hyp)
    mapping: Dict[str, str] = {}
    if ref_names and hyp_names:
        size = max(len(ref_names), len(hyp_names))
        # Square, padded with zeros: a speaker with no counterpart maps to
        # nothing and all its speech is confusion or a miss.
        cost = [[0] * size for _ in range(size)]
        for r, name in enumerate(ref_names):
            for h, other in enumerate(hyp_names):
                cost[r][h] = -len(ref[name] & hyp[other])
        for r, h in hungarian(cost):
            if r < len(ref_names) and h < len(hyp_names):
                mapping[hyp_names[h]] = ref_names[r]
    frames = set().union(*ref.values(), *hyp.values()) if (ref or hyp) else set()
    missed = false_alarm = confusion = total = 0
    for frame in frames:
        speaking = {name for name, f in ref.items() if frame in f}
        guessed = {name for name, f in hyp.items() if frame in f}
        n_ref, n_hyp = len(speaking), len(guessed)
        correct = len(speaking & {mapping.get(g) for g in guessed})
        total += n_ref
        missed += max(0, n_ref - n_hyp)
        false_alarm += max(0, n_hyp - n_ref)
        confusion += min(n_ref, n_hyp) - correct
    seconds = {"missed_s": missed * STEP_S, "false_alarm_s": false_alarm * STEP_S,
               "confusion_s": confusion * STEP_S, "speech_s": total * STEP_S}
    der = (missed + false_alarm + confusion) / total if total else 0.0
    return der, seconds


def _turns(payload: Any) -> List[Dict[str, Any]]:
    """Speaker turns from a prediction: ``[{start, end, speaker}]``, an
    audio-annotation ``{"segments": [...]}`` (label = speaker, times in
    seconds), or a tiered ``{"annotations": {tier: [...]}}`` (milliseconds)."""
    if isinstance(payload, dict) and isinstance(payload.get("annotations"), dict):
        from potato.training.audio import speaker_turns
        return speaker_turns(payload) or []
    if isinstance(payload, dict):
        payload = payload.get("segments") or payload.get("turns") or []
    out = []
    for entry in payload if isinstance(payload, list) else []:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start", entry.get("start_time"))
        end = entry.get("end", entry.get("end_time"))
        out.append({"start": start, "end": end,
                    "speaker": entry.get("speaker", entry.get("label"))})
    return out


def score_diarization(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """DER pooled over recordings (errors over total reference speech)."""
    errors = speech = 0.0
    parts = {"missed_s": 0.0, "false_alarm_s": 0.0, "confusion_s": 0.0}
    for target, payload in zip(gold, predicted):
        _, seconds = diarization_error(_turns(target), _turns(payload))
        for key in parts:
            parts[key] += seconds[key]
        errors += seconds["missed_s"] + seconds["false_alarm_s"] + seconds["confusion_s"]
        speech += seconds["speech_s"]
    if not speech:
        return {}
    der = errors / speech
    out = {"der": der, "diarization_accuracy": max(0.0, 1.0 - der),
           "speech_s": speech}
    out.update({key: value / speech for key, value in
                (("missed", parts["missed_s"]), ("false_alarm", parts["false_alarm_s"]),
                 ("confusion", parts["confusion_s"]))})
    return out
