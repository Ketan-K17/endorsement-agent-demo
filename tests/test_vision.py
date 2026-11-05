"""LLMVision against a fake structured model: the mapping around the model call."""

from __future__ import annotations

from typing import Any

import httpx
import openai
import pytest
from langchain_core.runnables import RunnableLambda

from endorsement_agent.runtime import Upload, VisionError
from endorsement_agent.vision import LLMVision, _Classified, _Read, _Reads

UPLOAD = Upload(doc_id="doc_1", filename="a.png", mime="image/png", data=b"x")


class FakeModel:
    """Returns `reply` from `with_structured_output`, or raises it if it is an exception."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.prompts: list[Any] = []
        self.kwargs: dict[str, Any] = {}

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        self.kwargs = kwargs

        def run(messages: Any) -> Any:
            self.prompts.append(messages)
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

        return RunnableLambda(run)


def vision(reply: Any) -> LLMVision:
    return LLMVision(FakeModel(reply))  # type: ignore[arg-type]


async def test_classify_keeps_a_known_type() -> None:
    c = await vision(_Classified(doc_type="rc", quality="ok", note=None)).classify(UPLOAD, ["rc"])
    assert (c.doc_type, c.quality) == ("rc", "ok")


async def test_classify_maps_an_unknown_type_to_other() -> None:
    reply = _Classified(doc_type="registration", quality="poor", note="blurred")
    c = await vision(reply).classify(UPLOAD, ["rc"])
    assert (c.doc_type, c.note) == ("other", "blurred")


async def test_extract_returns_exactly_the_requested_fields() -> None:
    reply = _Reads(
        fields=[
            _Read(name="reg_no", value="KA05MZ4182", confidence=0.9),
            _Read(name="registration", value="KA05MZ4182", confidence=0.9),
        ]
    )
    out = await vision(reply).extract(UPLOAD, "rc", ["reg_no", "owner_name"])
    assert set(out) == {"reg_no", "owner_name"}
    assert out["reg_no"].value == "KA05MZ4182"
    assert (out["owner_name"].value, out["owner_name"].confidence) == (None, 0.0)


async def test_extract_clamps_confidence_and_zeroes_null_values() -> None:
    reply = _Reads(
        fields=[
            _Read(name="a", value="x", confidence=7.0),
            _Read(name="b", value=None, confidence=0.9),
        ]
    )
    out = await vision(reply).extract(UPLOAD, "rc", ["a", "b"])
    assert out["a"].confidence == 1.0
    assert out["b"].confidence == 0.0


@pytest.mark.parametrize("printed", ["NA", "N/A", "n.a.", "Nil", "--", "None"])
async def test_extract_treats_printed_placeholders_as_absent(printed: str) -> None:
    reply = _Reads(fields=[_Read(name="hypothecated_to", value=printed, confidence=0.98)])
    out = await vision(reply).extract(UPLOAD, "rc", ["hypothecated_to"])
    assert (out["hypothecated_to"].value, out["hypothecated_to"].confidence) == (None, 0.0)


async def test_model_failure_is_a_vision_error_without_its_message() -> None:
    request = httpx.Request("POST", "https://example.test")
    error = openai.APIConnectionError(message="secret detail", request=request)
    with pytest.raises(VisionError) as e:
        await vision(error).classify(UPLOAD, ["rc"])
    assert "secret detail" not in str(e.value)


async def test_the_image_is_sent_with_strict_schema() -> None:
    model = FakeModel(_Classified(doc_type="rc", quality="ok", note=None))
    await LLMVision(model).classify(UPLOAD, ["rc"])  # type: ignore[arg-type]
    assert model.kwargs == {"method": "json_schema", "strict": True}
    part = model.prompts[0][1].content[0]
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
