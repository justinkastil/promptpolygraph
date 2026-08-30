"""Chunk-boundary redaction for `tokens_streamed` (GitHub #50 follow-up).

`tokens_streamed` is an arbitrary transport-level split of one body, so PII can
straddle two chunks. These tests pin the contract `scrub_response` now holds:
redaction is computed over the concatenation, and the result is written back as
a `list[str]` of unchanged length and order.
"""

from __future__ import annotations

import pytest

from promptpolygraph.models import Response
from promptpolygraph.service.privacy import (
    EMAIL_PLACEHOLDER,
    SSN_PLACEHOLDER,
    scrub_pii,
    scrub_response,
)

EMAIL = "jane.doe@example.com"
SSN = "123-45-6789"


class Resp:
    """Duck-typed stand-in, matching what the frozen accept script uses."""

    def __init__(self, text="hello", chunks=None):
        self.text = text
        self.tokens_streamed = chunks


def joined(resp):
    return "".join(resp.tokens_streamed)


# ─── the reported defect: PII split across a chunk boundary ──────────────────


@pytest.mark.parametrize(
    "chunks",
    [
        ["Contact jane.doe@", "example.com please"],
        ["Contact jane.", "doe@example", ".com please"],
        ["Contact jane.doe@example.co", "m please"],
        ["C", "o", "n", "t", "a", "c", "t", " ", *EMAIL, "!"],
    ],
    ids=["at-split", "three-way", "tld-split", "one-char-chunks"],
)
def test_email_split_across_chunks_does_not_survive(chunks):
    assert EMAIL in "".join(chunks), "fixture must actually split the address"

    out = joined(scrub_response(Resp(chunks=list(chunks))))

    assert EMAIL not in out
    assert "jane.doe@" not in out
    assert EMAIL_PLACEHOLDER in out


@pytest.mark.parametrize(
    "chunks",
    [
        ["SSN 123-45-", "6789 is assigned"],
        ["SSN 123", "-45-", "6789."],
        ["SSN 123-45-678", "9."],
        ["SSN ", *SSN, " done"],
    ],
    ids=["mid-split", "three-way", "last-digit", "one-char-chunks"],
)
def test_ssn_split_across_chunks_does_not_survive(chunks):
    assert SSN in "".join(chunks), "fixture must actually split the SSN"

    out = joined(scrub_response(Resp(chunks=list(chunks))))

    assert SSN not in out
    assert SSN_PLACEHOLDER in out


def test_joined_chunks_equal_scrub_pii_of_the_joined_input():
    """The whole point: chunking must not change *what* gets redacted."""
    chunks = ["mail jane.doe@", "example.com and ssn 123-45-", "6789 ok"]

    assert joined(scrub_response(Resp(chunks=chunks))) == scrub_pii("".join(chunks))


# ─── shape preservation ──────────────────────────────────────────────────────


def test_chunk_list_keeps_type_length_and_order():
    chunks = ["a ", "jane.doe@", "example.com", " b ", "123-45-", "6789", " c"]

    out = scrub_response(Resp(chunks=list(chunks))).tokens_streamed

    assert isinstance(out, list)
    assert all(isinstance(c, str) for c in out)
    assert len(out) == len(chunks)
    # Chunks that carried no PII are positionally untouched.
    assert out[0] == "a "
    assert out[3] == " b "
    assert out[6] == " c"


def test_placeholder_is_whole_in_the_chunk_where_the_match_began():
    """No chunk may hold a torn `[REDACTED-` fragment."""
    out = scrub_response(Resp(chunks=["Contact jane.doe@", "example.com!"])).tokens_streamed

    assert out == ["Contact " + EMAIL_PLACEHOLDER, "!"]
    for chunk in out:
        assert chunk.count("[") == chunk.count("]")


def test_chunk_fully_covered_by_an_earlier_placeholder_becomes_empty():
    """Emptied chunks are kept, not dropped: the chunk count is observable."""
    out = scrub_response(
        Resp(chunks=["ssn 123-", "45", "-6789", " tail"])
    ).tokens_streamed

    assert out == ["ssn " + SSN_PLACEHOLDER, "", "", " tail"]


def test_within_chunk_pii_still_redacts():
    """The single-chunk path from #50 must not regress."""
    out = scrub_response(
        Resp(chunks=["clean ", f"mail {EMAIL} and ssn {SSN}", " tail"])
    ).tokens_streamed

    assert out == ["clean ", f"mail {EMAIL_PLACEHOLDER} and ssn {SSN_PLACEHOLDER}", " tail"]


def test_scrubbing_is_idempotent_over_chunks():
    once = scrub_response(Resp(chunks=["Contact jane.doe@", "example.com"]))
    twice = scrub_response(Resp(chunks=list(once.tokens_streamed)))

    assert twice.tokens_streamed == once.tokens_streamed


# ─── degenerate and off-shape input is left untouched ────────────────────────


def test_clean_chunks_return_the_very_same_object():
    resp = Resp(chunks=["all ", "clean ", "here"])

    assert scrub_response(resp) is resp
    assert resp.tokens_streamed == ["all ", "clean ", "here"]


@pytest.mark.parametrize(
    "chunks",
    [None, [], "not a list", ("tuple", "of", "chunks"), 7],
    ids=["none", "empty", "str", "tuple", "int"],
)
def test_non_list_of_str_chunks_are_left_untouched(chunks):
    resp = Resp(text="clean", chunks=chunks)
    original = chunks

    out = scrub_response(resp)

    assert out is resp
    assert out.tokens_streamed is original


def test_mixed_element_list_is_left_untouched():
    """A list is only `list[str]` when *every* element is a str.

    A mixed list is off-shape for `Response.tokens_streamed`, so it is someone
    else's object: `scrub_response` leaves the value identical rather than
    partially rewriting it.
    """
    chunks = ["Contact jane.doe@example.com", None, 7]
    resp = Resp(text="clean", chunks=chunks)

    out = scrub_response(resp)

    assert out is resp
    assert out.tokens_streamed is chunks
    assert out.tokens_streamed == ["Contact jane.doe@example.com", None, 7]


def test_missing_tokens_streamed_attribute_is_tolerated():
    class NoChunks:
        text = f"mail {EMAIL}"

    out = scrub_response(NoChunks())

    assert EMAIL not in out.text
    assert not hasattr(out, "tokens_streamed")


# ─── the real pydantic model ─────────────────────────────────────────────────


def test_real_response_model_copies_rather_than_mutating():
    resp = Response(
        case_id="c1",
        text="Contact jane.doe@example.com",
        tokens_streamed=["Contact jane.doe@", "example.com"],
    )

    out = scrub_response(resp)

    assert out is not resp
    assert resp.tokens_streamed == ["Contact jane.doe@", "example.com"], "caller untouched"
    assert isinstance(out.tokens_streamed, list)
    assert len(out.tokens_streamed) == 2
    assert EMAIL not in "".join(out.tokens_streamed)
    assert EMAIL not in out.text
    # Round-trips through the model's own validation.
    assert Response.model_validate_json(out.model_dump_json()).tokens_streamed == (
        out.tokens_streamed
    )
