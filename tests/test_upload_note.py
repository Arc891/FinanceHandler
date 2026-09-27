"""
Tests for the optional /upload note: the household's context for one upload
("vakantie Italië 10-07 t/m 24-07"), given to the AI with every chunk.

The note is kept in the run state, so /resume categorises with it too; it is
shown in the summary; it is never logged, because it is free text.
"""

import logging

from automation.ai_categorizer import ClaudeCategorizer

from test_ai_parallel import ChunkProvider, EngineAI, categorizer, engine_with, run_batch, unmatched_rows

NOTE = "vakantie Italië 10-07 t/m 24-07"


def prompt_for(**kwargs):
    ai = ClaudeCategorizer.__new__(ClaudeCategorizer)
    anon = [{"booking_date": "12-07-2026", "credit_debit_indicator": "DBIT", "transaction_amount": 9.5,
             "creditor": "Merchant", "remittance_information": "gelato"}]
    return ai._build_batch_prompt(anon, [], [], {"Dates/uitjes": ""}, {}, {}, ["T1"], **kwargs)


def test_the_note_is_in_the_prompt_as_context_not_as_a_rule():
    prompt = prompt_for(user_context=NOTE)
    section = prompt.split("## Context from the household for this upload", 1)[1]
    assert NOTE in section.split("##", 1)[0]
    assert prompt.index("Context from the household") < prompt.index("## Transactions to Categorize")


def test_no_note_means_no_context_section():
    assert "Context from the household" not in prompt_for()
    assert "Context from the household" not in prompt_for(user_context="   ")


async def test_every_chunk_prompt_carries_the_note():
    seen = []

    class Recording(ChunkProvider):
        async def complete(self, prompt, **kw):
            seen.append(prompt)
            return await super().complete(prompt, **kw)

    await run_batch(categorizer(Recording()), unmatched_rows(90), user_context=NOTE)
    assert len(seen) == 3 and all(NOTE in p for p in seen)


async def test_the_engine_passes_the_note_to_the_batch():
    ai = EngineAI()
    await engine_with(ai).batch_categorize(unmatched_rows(2), context=NOTE, fallback_limit=0)
    assert ai.batch_kwargs["user_context"] == NOTE


async def test_upload_keeps_the_note_for_resume_shows_it_and_never_logs_it(tmp_path, caplog):
    from finance_core.run_state import RunStore
    from pipeline_env import Env, three_boundary_rows

    env = Env(tmp_path)
    with caplog.at_level(logging.DEBUG):
        upload_id, report = await env.upload(three_boundary_rows(), note=NOTE)
    assert env.engine.contexts and set(env.engine.contexts) == {NOTE}
    assert RunStore(str(env.runs_dir)).load(upload_id)["note"] == NOTE
    assert NOTE in report.text
    assert NOTE not in caplog.text


async def test_without_a_note_the_engine_gets_none(tmp_path):
    from pipeline_env import Env, three_boundary_rows

    env = Env(tmp_path)
    await env.upload(three_boundary_rows())
    assert env.engine.contexts and set(env.engine.contexts) == {None}
