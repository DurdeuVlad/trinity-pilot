"""Regression tests for semantic browser-side text extraction."""
from __future__ import annotations

from dataclasses import replace

import pytest

from trinity_core.adapters.browser import (
    TextCandidate,
    _extract_first_meaningful_text,
    _select_best_text_candidate,
)


def _candidate(
    text: str,
    *,
    tag: str = "p",
    top: float = 220,
    in_content_area: bool = True,
    in_preferred_scope: bool = False,
    block_child_count: int = 0,
    link_density: float = 0.0,
) -> TextCandidate:
    return TextCandidate(
        text=text,
        tag=tag,
        top=top,
        in_content_area=in_content_area,
        in_preferred_scope=in_preferred_scope,
        block_child_count=block_child_count,
        link_density=link_density,
    )


def test_select_best_text_candidate_prefers_real_paragraph_over_banner_copy() -> None:
    candidates = [
        _candidate("Subscribe to get the latest animal stories.", top=60, in_content_area=False),
        _candidate(
            "The cat is a domestic species of small carnivorous mammal. It is the only domesticated species in the family Felidae.",
            top=240,
        ),
    ]

    selected = _select_best_text_candidate(candidates)

    assert selected is not None
    assert selected.text.startswith("The cat is a domestic species")


def test_select_best_text_candidate_skips_wrapper_container_when_child_is_more_precise() -> None:
    wrapper = _candidate(
        "The Atlantic puffin is a species of seabird in the auk family. It breeds in colonies on coastal cliffs or offshore islands.",
        tag="div",
        block_child_count=4,
    )
    child = replace(wrapper, tag="p", block_child_count=0)

    selected = _select_best_text_candidate([wrapper, child])

    assert selected is not None
    assert selected.tag == "p"


def test_select_best_text_candidate_handles_non_wikipedia_pages_without_first_p_bias() -> None:
    candidates = [
        _candidate("Updated March 2026", top=120, in_content_area=False),
        _candidate(
            "A lunar eclipse occurs when the Moon moves into the Earth's shadow. This can happen only when the Sun, Earth, and Moon are aligned.",
            tag="div",
            top=260,
        ),
    ]

    selected = _select_best_text_candidate(candidates)

    assert selected is not None
    assert selected.text.startswith("A lunar eclipse occurs")


class _FakePage:
    def __init__(self, scoped_candidates: list[dict], global_candidates: list[dict]) -> None:
        self._scoped_candidates = scoped_candidates
        self._global_candidates = global_candidates

    async def wait_for_function(self, *_args, **_kwargs) -> None:
        return None

    async def eval_on_selector_all(self, *_args, **_kwargs) -> list[str]:
        return [candidate["text"] for candidate in self._scoped_candidates]

    async def evaluate(self, _script: str, args: dict) -> list[dict]:
        if args.get("selector"):
            return self._scoped_candidates + self._global_candidates
        return self._global_candidates


@pytest.mark.asyncio
async def test_extract_first_meaningful_text_falls_back_to_global_semantic_candidates() -> None:
    page = _FakePage(
        scoped_candidates=[
            {
                "text": "",
                "tag": "p",
                "top": 180,
                "in_content_area": True,
                "in_preferred_scope": True,
                "block_child_count": 0,
                "link_density": 0.0,
            },
            {
                "text": "Cats",
                "tag": "p",
                "top": 210,
                "in_content_area": True,
                "in_preferred_scope": True,
                "block_child_count": 0,
                "link_density": 0.0,
            },
        ],
        global_candidates=[
            {
                "text": "The cat is a domestic species of small carnivorous mammal. It is valued by humans for companionship.",
                "tag": "div",
                "top": 260,
                "in_content_area": True,
                "in_preferred_scope": False,
                "block_child_count": 0,
                "link_density": 0.0,
            }
        ],
    )

    selected = await _extract_first_meaningful_text(
        page,
        "#mw-content-text .mw-parser-output > p",
    )

    assert selected.startswith("The cat is a domestic species")
