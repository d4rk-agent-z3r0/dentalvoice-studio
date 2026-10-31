# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
import generate_audio_fixtures as fixtures


def test_committed_fixtures_match_the_catalogue_transcripts() -> None:
    assert fixtures.check(fixtures._clips()) == []


def test_check_reports_a_changed_transcript(monkeypatch: object) -> None:
    clips = fixtures._clips()
    clip_id, persona, text = clips[0]
    changed = [(clip_id, persona, text + " (edited)"), *clips[1:]]
    assert fixtures.check(changed) == [
        f"{clip_id}: transcript or voice changed since the audio was generated"
    ]
