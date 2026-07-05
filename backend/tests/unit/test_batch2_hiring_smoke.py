"""Regression test for the Batch 2 hiring JSON-parsing fix.

`extract_json_object` (aexy.llm.json_utils) recovers a JSON object from LLM
responses that wrap it in markdown fences or surrounding prose. Before this fix
the hiring service called `json.loads` directly on the raw response, which
failed on fenced output and silently fell back to a generic default JD/rubric.
The helper is now shared by hiring_intelligence, file_ai_pipeline, and the
Qwen OpenRouter vision provider.
"""

from aexy.llm.json_utils import extract_json_object


def test_extract_json_object_handles_fenced_and_prose():
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object("```\n{\"a\": 1}\n```") == {"a": 1}
    assert extract_json_object('intro\n```json\n{"role": "SDE"}\n```') == {"role": "SDE"}
    assert extract_json_object('prefix {"x": [1, 2]} suffix') == {"x": [1, 2]}


def test_extract_json_object_returns_none_on_unparseable():
    assert extract_json_object("garbage, not json") is None
    assert extract_json_object("") is None
    assert extract_json_object(None) is None
    assert extract_json_object("[1, 2, 3]") is None  # array, not an object
