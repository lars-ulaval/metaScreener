# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 11:57:09 2025

@author: alere
"""

# File: plugins/screen_A/prompts.py
# Batch 4 — Prompt templates (LLM integration)
# Adds:
#  - METADATA criterion-batched prompt (one criterion, N items)
#  - METADATA borderline cross-check prompt
#  - Explicit extractive-only evidence policy
#  - Helpers to build OpenAI Chat API message arrays

# -----------------------------
# Full-text (existing, kept)
# -----------------------------
FT_DECISION_PROMPT = """
You are screening scientific papers against inclusion/exclusion criteria.
Criterion: {criterion_json}
Use ONLY the provided evidence chunks (with page spans) to decide if the paper meets this criterion.
Return JSON with: decision in ["meet","not_meet","uncertain"], confidence in [0,1], and cite which chunks support your call.
""".strip()


# -----------------------------
# Metadata — shared constants
# -----------------------------

# Strict JSON schema (verbal form) the assistant must follow for metadata decisions
METADATA_DECISION_SCHEMA_TEXT = """
Output MUST be a JSON array. Each element corresponds to one item and has:
{
  "a_id": "<string or number>",         // echoes input item id
  "decisions": [
    {
      "criterion_id": "<string>",       // echoes the provided criterion id
      "decision": "meet" | "not_meet" | "uncertain",
      "confidence": <float 0..1>,
      "justification": {
        "field": "title" | "abstract" | "keywords" | "venue" | "lang" | "year",
        "quote": "<verbatim substring from that field>",
        "char_span": [<start_index>, <end_index>]   // 0-based, inclusive-exclusive
      }
    }
  ]
}
Do NOT include any additional keys. Do NOT include comments. Do NOT include trailing commas.
If you cannot find extractive evidence in the provided fields, set "decision":"uncertain" and omit the justification or set it to null.
""".strip()

# Extractive-only policy (to be embedded in system messages)
EXTRACTIVE_ONLY_POLICY = """
Rules you MUST follow:
1) Use ONLY the provided metadata fields for each item: title, abstract, keywords, venue, lang, year.
2) NO speculation or world knowledge. If evidence is missing or ambiguous, answer "uncertain".
3) For "meet" or "not_meet", you MUST provide extractive evidence: an exact substring ("quote") from one of the provided fields,
   with the field name and character span [start, end). If the quote is not a verbatim substring, your answer is invalid.
4) Keep temperature-like behavior deterministic: return a single best decision that the evidence supports.
5) Output MUST be valid JSON matching the schema exactly. Do NOT add explanations outside JSON.
""".strip()


# -----------------------------
# Metadata — criterion-batched
# -----------------------------

METADATA_CRITERION_BATCH_SYSTEM = f"""
You are assisting with metadata screening for a systematic review.

{EXTRACTIVE_ONLY_POLICY}

Your task: For ONE criterion and MANY items, decide for EACH item whether the item meets the criterion,
does not meet it, or is uncertain due to insufficient evidence. Then return STRICT JSON (array) as specified.

{METADATA_DECISION_SCHEMA_TEXT}
""".strip()

# The user content should carry the exact criterion and the list of items.
# Placeholders:
#   - {criterion_json}: a compact JSON object with id, type, scope="metadata", targets, logic/label, examples (optional)
#   - {items_json}: an array of item objects, each with: a_id, and only the fields present (title/abstract/keywords/venue/lang/year)
METADATA_CRITERION_BATCH_USER = """
{
  "criterion": {criterion_json},
  "items": {items_json}
}
""".strip()

def build_metadata_criterion_batched_messages(criterion_json: str, items_json: str, prompt_version: str = "v1"):
    """
    Returns a Chat API messages list for the criterion-batched metadata prompt.
    You should set: temperature=0, response_format=JSON (or post-validate).
    """
    system_msg = {
        "role": "system",
        "content": METADATA_CRITERION_BATCH_SYSTEM + f"\n\nPROMPT_VERSION: {prompt_version}"
    }
    user_msg = {
        "role": "user",
        "content": METADATA_CRITERION_BATCH_USER.format(criterion_json=criterion_json, items_json=items_json)
    }
    return [system_msg, user_msg]


# -----------------------------
# Metadata — borderline cross-check
# -----------------------------

# This prompt re-validates only borderline items, using quotes already discovered in earlier passes.
# It is cheaper: the model sees fewer items and is constrained to confirm/deny based on provided quotes.
METADATA_CROSSCHECK_SYSTEM = f"""
You are performing a BORDERLINE cross-check for metadata screening.

{EXTRACTIVE_ONLY_POLICY}

Task: For ONE criterion and a small set of borderline items, re-evaluate decisions using ONLY the provided fields
and the previously found QUOTES (spans). If the quotes contradict the criterion, you may switch to "not_meet".
If the quotes are insufficient or unclear, answer "uncertain". Return STRICT JSON (array) as specified.

{METADATA_DECISION_SCHEMA_TEXT}
""".strip()

# Placeholders:
#   - {criterion_json}: same as above
#   - {items_with_quotes_json}: array of items, each item may include a "prior_quotes":[{"field","quote","char_span"}] list
METADATA_CROSSCHECK_USER = """
{
  "criterion": {criterion_json},
  "items": {items_with_quotes_json}
}
""".strip()

def build_metadata_crosscheck_messages(criterion_json: str, items_with_quotes_json: str, prompt_version: str = "v1"):
    """
    Returns Chat API messages for the borderline cross-check prompt.
    Use this on the small 'borderline' tail to confirm/deny with stricter policy.
    """
    system_msg = {
        "role": "system",
        "content": METADATA_CROSSCHECK_SYSTEM + f"\n\nPROMPT_VERSION: {prompt_version}"
    }
    user_msg = {
        "role": "user",
        "content": METADATA_CROSSCHECK_USER.format(
            criterion_json=criterion_json,
            items_with_quotes_json=items_with_quotes_json
        )
    }
    return [system_msg, user_msg]


# -----------------------------
# Notes for callers (non-executable)
# -----------------------------
# - Always call models with temperature=0 and request JSON output (or parse/validate rigorously).
# - Truncate abstracts to a configured char limit BEFORE formatting items_json.
# - Only include fields that are actually present; missing fields should be omitted from items_json.
# - If a model returns any element without a valid extractive quote for a non-uncertain decision,
#   treat that element as "uncertain" in the fusion layer.
# - Consider including a small "examples_positive" / "examples_negative" field in criterion_json
#   when criteria are highly semantic; keep them short to save tokens.

# =============================
# Criteria Harmonization (NEW)
# =============================
from .criteria_schema import ALLOWED_TYPES, ALLOWED_SCOPE, ALLOWED_OPERATORS

# Verbal JSON schema the assistant must follow for CRITERIA harmonization
CRITERIA_HARMONIZE_SCHEMA_TEXT = f"""
Return STRICT JSON as either an array OR an object {{"criteria":[...]}}.
Each element has EXACTLY these fields:
{{
  "id": "<string>",                              // keep original id if present; otherwise assign C01, C02, ...
  "label": "<string>",                           // concise, normalized phrasing of the criterion
  "type": {" | ".join(sorted(ALLOWED_TYPES))!r},            // allowed only
  "scope": {" | ".join(sorted(ALLOWED_SCOPE))!r},           // allowed only
  "targets": ["<field>", ...],                   // e.g., "title","abstract","keywords","year","lang","venue"
  "operators": ["<op>", ...],                    // subset of {sorted(ALLOWED_OPERATORS)}
  "patterns": ["<string>", ...],                 // literal strings or regexes ONLY if operator == "regex"
  "weight": <float 0..10>,                       // clamp to range
  "threshold": <float 0..1>,                     // clamp to range
  "notes": "<string>"                            // optional editorial notes for humans
}}
Do NOT include extra keys, comments, or trailing commas.
""".strip()

CRITERIA_HARMONIZE_RULES = f"""
You rewrite and normalize screening criteria into a canonical schema.

Rules:
1) Use ONLY allowed values:
   - type ∈ {sorted(ALLOWED_TYPES)}
   - scope ∈ {sorted(ALLOWED_SCOPE)}
   - operators ⊆ {sorted(ALLOWED_OPERATORS)}
2) Be conservative. If in doubt, prefer scope "both" and operators ["contains"].
3) If one input line actually encodes multiple independent conditions, SPLIT into multiple criteria.
4) Normalize synonyms (e.g., "rct" → "randomized controlled trial") but keep the intended meaning.
5) Keep human intent; do NOT invent targets or operators without textual basis.
6) Prefer targets ["title","abstract","keywords"] unless the text clearly specifies other fields (e.g., "year ≥ 2015").
7) If operator requires numeric/ordered logic (e.g., "gte","lte","between"), ensure patterns reflect that intent (e.g., ["2015"] or ["2015;2020"]).
8) If no explicit patterns are provided, default "patterns" to ["<label>"].
9) Output MUST follow the strict JSON schema below.
""".strip()

CRITERIA_HARMONIZE_SYSTEM = f"""
You are assisting with CRITERIA HARMONIZATION for a systematic screening pipeline.

{CRITERIA_HARMONIZE_RULES}

{CRITERIA_HARMONIZE_SCHEMA_TEXT}
""".strip()

# The user message carries a compact payload of raw/deterministic criteria (array of dicts).
# Placeholders:
#  - {criteria_json}: array of criteria with fields like id,label,type,scope,targets,operators,patterns,weight,threshold,notes
CRITERIA_HARMONIZE_USER = """
{
  "criteria": {criteria_json}
}
""".strip()

def build_criteria_harmonize_messages(criteria_json: str, *, prompt_version: str = "v1") -> list[dict]:
    """
    Build Chat API messages for criteria harmonization.
    Call the model with temperature=0 and (ideally) response_format={"type":"json_object"}.
    """
    system_msg = {
        "role": "system",
        "content": CRITERIA_HARMONIZE_SYSTEM + f"\n\nPROMPT_VERSION: {prompt_version}"
    }
    user_msg = {
        "role": "user",
        "content": CRITERIA_HARMONIZE_USER.format(criteria_json=criteria_json)
    }
    return [system_msg, user_msg]
