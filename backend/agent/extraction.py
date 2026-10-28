"""Evidence file -> structured JSON (BUILD_SPEC §9). Quotes/invoices -> line items; photos -> verdict."""

from mandates.models import Evidence

from . import llm, prompts

NULLABLE_STR = {"type": ["string", "null"]}
NULLABLE_NUM = {"type": ["number", "null"]}

DOCUMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["supplier", "items", "total", "currency", "date", "notes"],
    "properties": {
        "supplier": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "key", "quantity", "unit_price"],
            "properties": {"name": {"type": "string"}, "key": NULLABLE_STR, "quantity": NULLABLE_NUM,
                           "unit_price": NULLABLE_NUM}}},
        "total": NULLABLE_NUM,
        "currency": {"type": "string"},
        "date": NULLABLE_STR,
        "notes": {"type": "string"},
    },
}

PHOTO_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "observed", "expected"],
    "properties": {
        "verdict": {"type": "string", "enum": ["matches", "does_not_match", "unclear"]},
        "observed": {"type": "string"},
        "expected": {"type": "string"},
    },
}

DOCUMENT_KINDS = (Evidence.QUOTE, Evidence.INVOICE, Evidence.RECEIPT)


class ExtractionError(Exception):
    pass


def _rules(evidence, kind):
    return [r for r in evidence.request.mandate.rules.all() if r.kind == kind]


def expected_milestone(evidence):
    for rule in _rules(evidence, "requires_evidence"):
        if rule.params.get("kind") == Evidence.MILESTONE_PHOTO:
            return rule.params.get("label") or "the agreed milestone"
    return "the agreed milestone"


def item_keys(evidence):
    return sorted({r.params["item"] for r in _rules(evidence, "price_ceiling")})


def _image(evidence):
    upload = evidence.upload
    if upload is None:
        raise ExtractionError("No file attached")
    if not upload.is_image:
        raise ExtractionError("Please send a photo (JPEG or PNG) of the document")
    return bytes(upload.data), upload.content_type


def extract(evidence):
    """Read the evidence file with the vision model and store the result on the Evidence."""
    image = _image(evidence)
    if evidence.kind == Evidence.MILESTONE_PHOTO:
        prompt = prompts.render("extract_photo", expected=expected_milestone(evidence))
        result, model = llm.structured(prompt, PHOTO_SCHEMA, name="milestone_photo", images=[image])
    else:
        keys = item_keys(evidence)
        prompt = prompts.render("extract_document", kind_label=evidence.get_kind_display().lower(),
                                item_keys=", ".join(keys) if keys else "(none)")
        result, model = llm.structured(prompt, DOCUMENT_SCHEMA, name="document", images=[image])
        result["items"] = [i for i in result.get("items", []) if i.get("unit_price") is not None]
    evidence.extracted = result
    evidence.model_name = model
    evidence.save(update_fields=["extracted", "model_name", "updated_at"])
    return evidence
