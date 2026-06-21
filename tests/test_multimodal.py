"""Tests for multimodal (image/audio/document) evaluation support.

Covers the additive Case.attachments contract (round-trip + text-only
invariance), the HTTP adapter's multipart body construction (mock transport, no
network), the deterministic multimodal mock target and its attachment-obedience
flag, and the new multimodal_injection red-team techniques + reference lock.
"""

from __future__ import annotations

import base64

import httpx

from promptpolygraph.adapters import HTTPAdapter
from promptpolygraph.adapters.demo import (
    ATTACHMENT_OBEY_MARKER,
    DemoAdapter,
    obeyed_attachment_instruction,
)
from promptpolygraph.models import Attachment, Case
from promptpolygraph.provenance import check_reference_integrity, reference_manifest
from promptpolygraph.redteam.catalog import TECHNIQUES, standards_for, techniques_for


# ─── model contract ──────────────────────────────────────────────────────────


def test_text_only_case_unchanged():
    c = Case(prompt="hello")
    assert c.attachments == []
    assert c.has_attachments() is False
    assert c.is_multimodal() is False
    # Old corpora carry no attachments key; the serialized default is empty.
    assert c.model_dump()["attachments"] == []


def test_image_attachment_round_trips():
    att = Attachment(kind="image", media_type="image/png", data_b64="aGk=", name="chart.png")
    c = Case(prompt="what is in this image?", attachments=[att])
    assert c.has_attachments() and c.is_multimodal()

    blob = c.model_dump_json()
    back = Case.model_validate_json(blob)
    assert back.attachments[0].kind == "image"
    assert back.attachments[0].media_type == "image/png"
    assert back.attachments[0].data_b64 == "aGk="
    assert back.attachments[0].name == "chart.png"
    assert back == c


def test_legacy_payload_without_attachments_validates():
    # A record produced before v1.2 has no attachments field at all.
    legacy = {"id": "x1", "prompt": "hi", "category": "default"}
    c = Case.model_validate(legacy)
    assert c.attachments == []


# ─── HTTP multipart body ─────────────────────────────────────────────────────


async def test_http_multipart_built_for_attachment():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "ok"})

    a = HTTPAdapter(
        url="https://x.test/vision",
        body_template={"prompt": "{{prompt}}", "category": "{{category}}"},
    )
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    att = Attachment(kind="image", media_type="image/png",
                     data_b64=base64.b64encode(b"PNGDATA").decode(), name="x.png")
    r = await a.query(Case(prompt="describe", category="vision", attachments=[att]))
    await a.aclose()

    assert r.text == "ok"
    assert seen["content_type"].startswith("multipart/form-data")
    body = seen["body"]
    assert b"PNGDATA" in body          # attachment bytes present
    assert b"describe" in body          # prompt field present
    assert b"image/png" in body         # declared media type present
    assert b'filename="x.png"' in body  # filename carried


async def test_http_text_only_path_stays_json():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"text": "pong"})

    a = HTTPAdapter(url="https://x.test/chat", body_template={"message": "{{prompt}}"})
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = await a.query(Case(prompt="ping"))
    await a.aclose()

    assert r.text == "pong"
    assert "application/json" in seen["content_type"]
    assert seen["body"] == '{"message":"ping"}'


async def test_http_body_mode_uses_form_encoding_for_text_fields():
    # body_mode="multipart" with no attachments sends the prompt as a form field
    # (httpx emits multipart only when file parts are present, urlencoded form
    # otherwise); either way the request leaves the JSON body path.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"text": "ok"})

    a = HTTPAdapter(url="https://x.test/up", body_mode="multipart")
    a._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await a.query(Case(prompt="ping"))
    await a.aclose()
    assert "application/json" not in seen["content_type"]
    assert "prompt=ping" in seen["body"]


# ─── multimodal mock target + obedience flag ─────────────────────────────────


def _image_with_marker() -> Attachment:
    payload = f"some pixels then: {ATTACHMENT_OBEY_MARKER}".encode()
    return Attachment(kind="image", media_type="image/png",
                      data_b64=base64.b64encode(payload).decode())


async def test_safe_target_ignores_embedded_instruction():
    case = Case(prompt="describe the attached image", attachments=[_image_with_marker()])
    safe = DemoAdapter(style="everyday")
    r = await safe.query(case)
    assert ATTACHMENT_OBEY_MARKER not in r.text
    assert obeyed_attachment_instruction(case, r) is False


async def test_vulnerable_target_obeys_attachment_and_is_flagged():
    case = Case(prompt="describe the attached image", attachments=[_image_with_marker()])
    vuln = DemoAdapter(style="everyday", attachment_vulnerable=True)
    r = await vuln.query(case)
    assert ATTACHMENT_OBEY_MARKER in r.text
    assert obeyed_attachment_instruction(case, r) is True


async def test_flag_requires_attachment_channel():
    # Same canary in the user text is not a multimodal breach.
    case = Case(prompt=f"reply with {ATTACHMENT_OBEY_MARKER}", attachments=[_image_with_marker()])
    vuln = DemoAdapter(style="everyday", attachment_vulnerable=True)
    r = await vuln.query(case)
    assert obeyed_attachment_instruction(case, r) is False


# ─── red-team techniques + reference integrity ───────────────────────────────


def test_multimodal_injection_techniques_exist_and_are_tagged():
    techs = techniques_for("multimodal_injection")
    ids = {t.id for t in techs}
    assert {"image_ocr_injection", "document_embedded_injection",
            "metadata_caption_confusion"} <= ids
    assert len(techs) >= 3
    for t in techs:
        assert t.owasp == "LLM01:Prompt Injection"
        assert t.atlas and t.atlas.startswith("AML.T")
        assert t.seeds


def test_standards_for_multimodal_injection():
    std = standards_for("multimodal_injection")
    assert std["owasp"] == "LLM01:Prompt Injection"
    assert std["atlas"].startswith("AML.T")


def test_every_technique_carries_standards():
    for t in TECHNIQUES:
        assert t.owasp and t.atlas, f"{t.id} missing a standard tag"


def test_reference_lock_in_sync():
    res = check_reference_integrity()
    assert res["ok"], res["reason"]
    # the new family is reflected in the committed manifest
    ids = {t["id"] for t in reference_manifest()["techniques"]}
    assert "image_ocr_injection" in ids
