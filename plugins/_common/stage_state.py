# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/stage_state.py — what state an LLM stage is in, as plain data.

Every decision in here used to be an expression inside a Tk callback, which
made it untestable: ``tests/conftest.py`` replaces ``tkinter`` with a
``MagicMock``, so ``ttk.Frame`` is a mock and ``ELView`` cannot be
instantiated at all. Nothing in the suite asserted on a status label or a
button state, and the defects this module exists to fix — F-93, F-111,
F-118 — all live in exactly those expressions.

So the rule here is: **inputs are plain data, outputs are plain data, and
nothing imports Tk.** The View's job becomes reading widgets, calling one
of these, and writing widgets.

**Two arms, because the inputs arrive at two different times and answer two
different questions.** Before a run, the only facts available are
configuration — is a bundle loaded, is a key visible, is the model field
non-empty — and the question is *may I start, and if not, why not*. After a
run, the facts are the outcome counts and the run report the engine now
returns, and the question is *did that work, and may I export it*. A single
flat enumeration would have to mix the two, and §B1.4's own eleven-state
table does mix them: state 10 ("model blank") is a pre-run check, states
2–7 are probe results, and the post-run states are absent from it entirely
because that section was written about model discovery. Keeping the arms
separate is what lets wave 10 add its three endpoint states to the first
arm without touching the second.

*(Wave 8 part 2. Movement one of this file is a behaviour-preserving
extraction: ``control_states`` and ``run_outcome`` reproduce what the two
Views already did, expression for expression, so the characterisation tests
in ``tests/test_stage_state.py`` lock in today's behaviour — defects
included — before any of it is changed.)*
"""
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple

from plugins._common.bundle import (
    CANCELLED_EXPORT_REASON,
    EXCLUSION_SUPPRESSED,
    NOT_SCREENED,
    _run_summary_counts_text,
)


# ----------------------------
# Outcome — what the last run amounted to
# ----------------------------

OUTCOME_CANCELLED = "cancelled"
OUTCOME_NOT_SCREENED = "not_screened"
OUTCOME_NO_ANSWERS = "no_answers"
OUTCOME_NOTHING_SEPARATED = "nothing_separated"
OUTCOME_PARTIAL_FAILURE = "partial_failure"
OUTCOME_OK = "ok"

#: Wave 12, F-145. Added as a new member per this vocabulary's extension
#: contract — no existing state changed meaning.
OUTCOME_EXCLUSIONS_SUPPRESSED = "exclusions_suppressed"

OUTCOME_CODES = (
    OUTCOME_CANCELLED, OUTCOME_NOT_SCREENED, OUTCOME_NO_ANSWERS,
    OUTCOME_NOTHING_SEPARATED, OUTCOME_PARTIAL_FAILURE, OUTCOME_OK,
    OUTCOME_EXCLUSIONS_SUPPRESSED,
)
"""The closed set of states a finished run can be in.

The first two and the last are what the code distinguished before wave 8;
the middle three are the ones it could not, and they are the reason a
server that was down, a model name with a typo, a model that was never
pulled, an empty model field and a genuinely all-uncertain corpus all
reported ``"EL done."``.
"""


@dataclass(frozen=True)
class Outcome:
    """What the interface should say about the run that just finished.

    ``code``
        one of :data:`OUTCOME_CODES`. The thing to branch on.
    ``label``
        the status line, verbatim.
    ``ack_reason``
        the question the user must answer yes to before exporting, or
        ``None`` when export needs no acknowledgement. Rendered here rather
        than in ``plugins/_common/bundle.py`` only to keep the import
        one-way — ``bundle`` must not import this module, because this
        module imports ``bundle``.
    """

    code: str
    label: str
    ack_reason: Optional[str] = None


def run_outcome(*, stage: str, counts: Mapping[str, int],
                llm_report: Mapping[str, Any], cancelled: bool,
                not_screened: bool, total_rows: int) -> Outcome:
    """Classify a finished run.

    The first two branches and the last are the Views' own, transcribed in
    movement one; the middle two are F-111. The ordering is load-bearing
    throughout, and each step is the more specific cause winning over the
    more general one:

    1. **cancelled** beats everything. A run that stopped early tells you
       nothing about what it would have screened.
    2. **no criteria** (F-34) beats everything below it, because a stage
       that evaluated nothing cannot have failed to get an answer.
    3. **no answers** beats *nothing separated*, because a dead server also
       separates nothing — and the two call for opposite responses from the
       user, so reporting the general case would send them looking in the
       wrong place.
    4. **nothing separated** is the honest name for the case where the
       model *was* heard from and no record cleared the evidence gate. It
       is a screening result, not a misconfiguration, and it may well be
       genuine.
    5. **partial failure** is a real result with a documented hole.

    ``llm_report`` is the engine's, not re-derived here. The counting
    substrate exists (wave 8 part 1) and a second derivation would be two
    representations of one fact — F-69's shape, which this project has
    shipped four times. Unknown keys are ignored and missing keys default,
    so wave 9's provenance fields and an older build's absent report are
    both non-events.
    """
    if cancelled:
        return Outcome(
            code=OUTCOME_CANCELLED,
            label="Cancelled — partial run, nothing exported.",
            ack_reason=None,
        )
    if not_screened:
        return Outcome(
            code=OUTCOME_NOT_SCREENED,
            label=_run_summary_counts_text(
                counts, stage=stage, total_rows=total_rows),
            ack_reason=None,
        )

    records = int(llm_report.get("records", 0) or 0)
    answered = int(llm_report.get("answered", 0) or 0)
    failed = int(llm_report.get("failed", 0) or 0)
    rejected = int(llm_report.get("decisions_rejected", 0) or 0)
    calls_failed = int(llm_report.get("calls_failed", 0) or 0)
    # From the outcome histogram the engine already built, not re-derived
    # by re-scanning the rows: two representations of one fact with nothing
    # forcing them to agree is F-69's shape, which this project has shipped
    # four times.
    suppressed = int(counts.get(EXCLUSION_SUPPRESSED, 0) or 0)
    # F-153. A suppressed record received a confident verdict that passed
    # the evidence gate; the only reason it is not in `OUT` is that policy
    # declined to act. Counting it as separated is what keeps the
    # `nothing_separated` gate meaning the same thing under both policies
    # — see the branch below for why that equivalence is the requirement.
    separated = (int(counts.get("OUT", 0) or 0)
                 + int(counts.get("PASS_CLEAN", 0) or 0)
                 + suppressed)

    if records and answered == 0:
        return Outcome(
            code=OUTCOME_NO_ANSWERS,
            label=(f"{stage}: NO ANSWERS — 0 of {records} record-criterion "
                   f"pairs carry a decision ({failed} failed)."),
            ack_reason=(
                f"{stage} did not obtain a usable answer for a single "
                f"record.\n\n"
                f"{failed} of {records} record-criterion pairs ended in a "
                f"failed call, and {calls_failed} call(s) raised. Every "
                f"record is therefore flagged rather than screened, and an "
                f"exported bundle will record that outcome as though the "
                f"stage had run normally.\n\n"
                f"This is what an unreachable server, a misspelled model "
                f"name, a model that was never pulled and a rejected key all "
                f"look like. The Log tab names the cause of each failed "
                f"call.\n\n"
                f"Export anyway?"
            ),
        )

    if total_rows and separated == 0:
        return Outcome(
            code=OUTCOME_NOTHING_SEPARATED,
            label=(f"{stage}: nothing separated — every record flagged "
                   f"(model answered {answered} of {records})."),
            ack_reason=(
                f"{stage} separated none of the {total_rows} records: none "
                f"was excluded and none passed cleanly.\n\n"
                f"The model was heard from — {answered} of {records} "
                f"record-criterion pairs carry a decision — so this is a "
                f"screening result rather than a misconfiguration, and it "
                f"may well be genuine: a corpus the model is unsure about "
                f"produces exactly this. Every record is recorded as "
                f"flagged for human review.\n\n"
                f"Export anyway?"
            ),
        )

    if suppressed:
        # F-153, the wave 12 review's confirmed finding. This branch used
        # to sit ABOVE the one now above it, guarded on `if suppressed:`
        # alone, so **one** suppressed record among nineteen unresolved
        # ones cancelled the export acknowledgement for the whole run —
        # turning a degenerate result into a silent export, and doing it
        # most readily for the weak local models flag-only exists for.
        #
        # The repair is in `separated` rather than here: a suppressed
        # record *did* receive a confident, gate-passing verdict, so it is
        # work done and counts toward "this stage separated something".
        # A run with nothing separated and nothing suppressed still gets
        # its gate.
        #
        # That also keeps the two policies judging run quality
        # identically, which is the property that matters: under
        # exclusion-permitted the same model behaviour gives 1 OUT and 19
        # flagged, `separated == 1`, and no acknowledgement. Flag-only
        # must not be stricter about an outcome the model produced
        # either way.
        gaps = (f" {failed} failed and {rejected} unreadable of {records}."
                if (failed or rejected) else "")
        return Outcome(
            code=OUTCOME_EXCLUSIONS_SUPPRESSED,
            label=(f"{stage} done, flag-only — {suppressed} record(s) carry "
                   f"a model exclusion that was not acted on.{gaps}"),
            # None, deliberately. **This branch exists to stop a second
            # F-34.** Suppressing every exclusion drives OUT to zero, so
            # without it the branch below would fire on a run that was
            # correctly configured, fully successful and doing exactly what
            # the user asked — reporting "nothing separated — every record
            # flagged" and demanding an acknowledgement to export. F-34 was
            # a stage using a label that asserted the opposite of the
            # truth; asking a user to acknowledge a working safety gate as
            # damage would be the same error with the sign flipped.
            ack_reason=None,
        )

    if failed or rejected:
        return Outcome(
            code=OUTCOME_PARTIAL_FAILURE,
            label=(f"{stage} done, with gaps — {failed} failed and "
                   f"{rejected} unreadable of {records}."),
            ack_reason=None,
        )

    return Outcome(code=OUTCOME_OK, label=f"{stage} done.", ack_reason=None)


# ----------------------------
# Readiness — whether a run may start at all
# ----------------------------

READY = "ready"
NO_BUNDLE = "no_bundle"
NO_KEY = "no_key"
NO_MODEL = "no_model"

#: Wave 11 session B. Added as new members, per this vocabulary's own
#: extension contract below — no existing state changed meaning.
NOT_CONFIGURED = "not_configured"
NOT_CHECKED = "not_checked"
ENDPOINT_UNREACHABLE = "endpoint_unreachable"
NO_MODELS_PULLED = "no_models_pulled"

READINESS_CODES = (READY, NO_BUNDLE, NO_KEY, NO_MODEL,
                   NOT_CONFIGURED, NOT_CHECKED, ENDPOINT_UNREACHABLE,
                   NO_MODELS_PULLED)
"""The closed set of pre-run states, over the inputs available today.

**Wave 10 extends this set, and the extension is the point of the split.**
Once an endpoint is a first-class GUI value, three more states become
decidable — endpoint unreachable, endpoint reachable but the model was
never pulled, and a keyless server that must not be blocked for want of a
key. Each is a new member here and a new branch in ``llm_readiness``,
reached by new keyword arguments; none of them changes a state that already
exists. §B1.4's six *discovery* states (0, 4, 5, 6, 7, 9) arrive the same
way and for the same reason.
"""


#: Providers that authenticate. Everything else is assumed to, because
#: refusing to run costs a click while guessing that an unknown endpoint
#: is unauthenticated could leak a key or spend money.
_KEYLESS_PROVIDERS = ("local", "custom")


def key_required(provider: str) -> bool:
    """Whether this provider needs an API key at all (F-117, D1).

    The unification point. There were two predicates over one environment
    variable: ``llm_client._has_openai_key`` stripped, and the
    harmoniser's ``_llm_available`` used bare ``os.getenv`` truthiness —
    so a whitespace-only key made the harmoniser offer to spend money
    while EL and IL refused.

    Making both strip would have left the deeper defect. A local server
    does not authenticate, so under a *presence* check the local user must
    invent a placeholder credential to pass a gate that exists for a
    provider they are not using — which is exactly what the old ``NO_KEY``
    message instructed them to do. The question is therefore about the
    provider, not about the string.
    """
    return (provider or "").strip().lower() not in _KEYLESS_PROVIDERS


#: The per-record lists an engine fills for each criterion, named once.
#: F-156: the Views enumerated four of these inline, in four places, and
#: F-145 added a fifth to the engine without the Views hearing about it —
#: so the drill-down hid exactly the records flag-only exists to surface.
#: Enumerated here so a sixth cannot be added on one side only.
CRITERION_ROW_LISTS = ("failed", "missing", "met", "uncertain", "suppressed")


def criterion_touched(ev: Mapping[str, Any], cid: str) -> bool:
    """Whether this criterion had anything to say about this record.

    The predicate behind the criteria table's drill-down: click a
    criterion, see the records it acted on. "Acted on" means *any* of
    :data:`CRITERION_ROW_LISTS`, including ``suppressed`` — a verdict the
    model reached and policy declined to act on is still something the
    criterion said, and it is the case a reviewer most needs to read.

    Tolerant of a missing or ``None`` list, because the Views pass a
    default dict when ``row_eval_lists`` is shorter than ``full_rows``.
    """
    for key in CRITERION_ROW_LISTS:
        if cid in (ev.get(key) or ()):
            return True
    return False


def exclusion_allowed(*, provider: str, setting: Any = None) -> bool:
    """Whether an LLM verdict from this provider may REMOVE a record.

    Wave 12, F-145. A local model can read and annotate; it cannot be
    trusted to remove a paper from a systematic review. The measurement
    that establishes this is quoted in full in
    ``tests/test_flag_only.py``: over the same 85-record corpus and the
    same criteria as the committed goldens, gpt-4o-mini produced one
    exclusion (audited, correct), llama3.2:latest produced 40 and 43
    over two runs of an identical recorded configuration (not
    individually audited; 39 and 42 of them were records the audited run
    kept) and qwen2.5:7b produced 4 (all four examined individually and
    wrong, confirmed by the author). Every one of those exclusions
    **passed the evidence gate**, with a verbatim quote above threshold
    — ``_quote_in_text``
    verifies that a quote is real, and nothing here can verify that a
    quote is relevant.

    ``setting`` is the user's explicit choice and wins outright when it is
    a genuine boolean. Anything else — ``None``, an absent key, or the
    ``"no"`` a hand-edited settings file might carry — means *nobody has
    chosen*, and the provider answers. The type guard is deliberate and is
    the direction of harm that matters: ``bool("no")`` is ``True``, so
    coercing would silently PERMIT a local model to exclude.

    **The default is computed here rather than stored**, for the reason
    ``defaults()`` gives about ``provider`` and ``batch_size``: a boolean
    written to disk at install time is wrong the moment the provider
    changes, and a module that cannot see the input a decision depends on
    must not assert a value.

    The provider question is ``key_required``'s, not a second predicate of
    this module's own. That is F-117's rule — one predicate per question,
    because two that answer the same question drift — and it is not a
    coincidence being exploited: a keyless provider *is* a local or
    self-hosted engine, which is exactly the population the measurement
    covers. ``UNCHOSEN`` is not keyless and therefore is not restricted,
    which also keeps the golden replays byte-identical, since
    ``tests/conftest.py`` isolates the settings directory and every replay
    resolves ``provider=""``.

    Note what this deliberately does **not** ask. ``key_required_for``'s
    (provider, endpoint) pair is the right question for *money*, and
    INV-1b must keep asking it. Here the provider alone is the right
    question, and where the two disagree this one errs toward flagging —
    a "local" provider aimed at the vendor is over-restricted, which costs
    a reviewer five more abstracts, while the reverse error costs a
    silently missing study.
    """
    if isinstance(setting, bool):
        return setting
    return key_required(provider)


#: Hosts that bill. Held as bare strings rather than derived from
#: ``settings.DEFAULT_OPENAI_ENDPOINT`` because that module imports this
#: one; ``tests/test_stage_endpoint_invariant.py`` asserts the two agree,
#: so they cannot drift apart silently.
PAID_VENDOR_HOSTS = ("api.openai.com",)

#: The code points IDNA folds to an ASCII full stop, so a host carrying
#: one is the same host to DNS and a different string to a comparison
#: (F-152). RFC 3490 §3.1 names exactly these three besides U+002E.
_IDNA_FULL_STOPS = {
    0x3002: ".",        # IDEOGRAPHIC FULL STOP
    0xFF0E: ".",        # FULLWIDTH FULL STOP
    0xFF61: ".",        # HALFWIDTH IDEOGRAPHIC FULL STOP
}


def is_paid_vendor(endpoint: Optional[str]) -> bool:
    """Whether this endpoint is a host that charges for the call.

    Parsed as a URL rather than matched as a substring: ``https://
    api.openai.com/v1`` and ``https://api.openai.com:443/v1/`` are the
    same host, while ``http://api.openai.com.example.invalid/v1`` is not
    — and a substring check would get the last one wrong in the direction
    that costs money.

    A value with no scheme is parsed as though it had one, because a user
    typing an endpoint by hand routinely omits it and the answer must not
    depend on that.
    """
    raw = (endpoint or "").strip()
    if not raw:
        return False
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(raw if "//" in raw else "//" + raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        # **F-152. This used to raise rather than answer.** `urlsplit`
        # raises `ValueError: Invalid IPv6 URL` on inputs a user can type
        # (`http://[::1`), and this predicate is called from
        # `key_required_for` -> `key_ok` -> `llm_readiness`, i.e. from
        # inside Tk callbacks during widget construction, where an
        # exception does not surface as an error message.
        #
        # `True` is the answer, not `False`. An endpoint this code cannot
        # parse is one it cannot prove is *not* the vendor, and INV-1's
        # own rule decides the direction: refusing to run costs a click,
        # while guessing "not the vendor" waives the key gate and bills.
        return True

    # **Every character DNS treats as a label separator, not just the
    # ASCII one.** Session C's review found `api.openai.com.` — the
    # fully-qualified form — defeating a plain string comparison, so a
    # `rstrip(".")` was added and INV-1's fourth route closed.
    #
    # F-152 is the fifth, and it is the same defect in a wider alphabet.
    # IDNA (RFC 3490 §3.1) treats U+3002, U+FF0E and U+FF61 as full stops
    # exactly as it treats U+002E, so `api.openai.com．` encodes to
    # `api.openai.com.` and resolves to the identical server — measured,
    # not assumed: `"api.openai.com．".encode("idna")` returns
    # `b"api.openai.com."`. The request went to the paid vendor while
    # this returned False and the keyless gate stayed open.
    #
    # Normalised before the strip rather than added to it, so that an
    # interior one (`api．openai．com`) is also the same host.
    host = host.translate(_IDNA_FULL_STOPS).rstrip(".")
    return host in PAID_VENDOR_HOSTS


def key_required_for(provider: str, endpoint: Optional[str] = None) -> bool:
    """Whether this **resolved pair** needs an API key.

    **Wave 11 session C. The provider string alone stopped being
    sufficient the moment a stage could point somewhere else.**

    Session B closed the wave's billing defect with an invariant over the
    class: *a keyless provider never resolves to the paid vendor*. That
    is a rule about the **fallback** — it fires when nothing named an
    endpoint. A per-stage endpoint override reaches the vendor
    **explicitly**, so the rule does not fire, and the combination

        provider="local"  (``key_required`` is False, gate waived)
        stages["EL"]["endpoint"] = "https://api.openai.com/v1"

    is a keyless stage pointed straight at the paid vendor, with
    ``placeholder_key_for`` supplying the literal string ``"local"`` as
    the credential — or the user's real key if one is stored. That is the
    same harm this wave has now produced twice, by a third route.

    So the question is asked about the pair, and where the two halves
    disagree the **safe** side wins: an endpoint that bills requires a
    key whatever the provider field says. Refusing to run costs a click;
    guessing that a billing endpoint is free spends money.

    ``key_required`` is left exactly as it was and is still the answer
    when no endpoint is known — one predicate, now asking a slightly
    larger question, rather than two.
    """
    return key_required(provider) or is_paid_vendor(endpoint)


def key_ok(*, provider: str, api_key: Optional[str],
           endpoint: Optional[str] = None) -> bool:
    """Whether this configuration's key requirement is satisfied.

    ``endpoint`` defaults to unknown, which reduces to exactly the
    provider-only question this asked before — so every existing caller
    keeps its meaning and only the ones that know where the stage points
    get the stronger check.
    """
    if not key_required_for(provider, endpoint):
        return True
    return bool((api_key or "").strip())


@dataclass(frozen=True)
class Readiness:
    """Whether the stage may start, and what to say if not.

    ``model`` is the *normalised* model — stripped — so the caller uses this
    rather than re-deriving it. Two places deciding what the model is was
    how F-93 happened.
    """

    code: str
    can_run: bool
    label: str
    detail: str
    model: str = ""


def llm_readiness(*, stage: str, has_bundle: bool, provider: str,
                  api_key: Optional[str], model: Optional[str],
                  probe: Any = None, endpoint: Optional[str] = None
                  ) -> Readiness:
    """Decide whether an LLM stage may start.

    The order is the order the user encounters the steps in, so a user with
    nothing set up is told to load a bundle rather than sent to find an API
    key. Each check names the single next thing to fix.

    **F-117 replaced ``has_key: bool`` with ``provider`` and ``api_key``**,
    which is the extension ``READINESS_CODES`` anticipates. A boolean could
    not express "this provider needs no key", so the local user was sent to
    invent a placeholder. The parameter was *removed* rather than kept as a
    deprecated alias: a caller left on ``has_key=`` would silently keep the
    presence check, and two predicates is the defect being closed. A
    ``TypeError`` is the cheaper failure.

    F-93 lives in the last one. ``(self.var_model.get() or
    DEFAULT_MODEL).strip()`` put the strip *outside* the ``or``, so a
    whitespace-only field is truthy, survives the fallback and reaches the
    engine as ``""`` — which the engine takes as "no model" and skips
    silently, producing a full corpus of unscreened records and a status
    line reading "done".
    """
    if not has_bundle:
        return Readiness(
            code=NO_BUNDLE, can_run=False, label="No bundle loaded",
            detail=f"Load a ScreenA bundle ZIP before running {stage}.",
        )
    # Wave 11 session B. Before anything about keys or models: has a
    # provider been *chosen*? `key_required("local")` is False, so local
    # waives the key gate — correct once chosen, catastrophic before.
    # Session A shipped `provider="local"` as a default and left a fresh
    # install worse off than before that wave: previously blocked at
    # NO_KEY, afterwards waved through and billed. D1 describes what the
    # popup SHOWS; it says nothing about what is true before the choice
    # exists. So an unchosen provider blocks here, ahead of every check
    # that could otherwise be satisfied and make the path look complete.
    if not (provider or "").strip():
        return Readiness(
            code=NOT_CONFIGURED, can_run=False, label="No provider",
            detail=(
                f"{stage} has no model provider yet.\n\n"
                f"Choose one — a local model, or a hosted provider — and "
                f"metaScreener will remember it for next time. The "
                f"deterministic stages do not need one and are unaffected."
            ),
        )
    # Wave 11 session C. The key question is asked about the resolved
    # PAIR. A stage whose endpoint override points at the paid vendor
    # needs a key however keyless its provider claims to be — see
    # `key_required_for`. `endpoint=None` means "not known here", which
    # reduces to the provider-only question every earlier caller asked.
    if not key_ok(provider=provider, api_key=api_key, endpoint=endpoint):
        billing = is_paid_vendor(endpoint) and not key_required(provider)
        return Readiness(
            code=NO_KEY, can_run=False, label="API key ✗",
            detail=(
                (f"{stage} is pointed at {endpoint}, which bills for every "
                 f"call, and no API key is set.\n\n"
                 f"The provider is set to '{provider}', which normally needs "
                 f"no key — but the endpoint decides who is billed, not the "
                 f"provider name. Enter a key, or point {stage} back at a "
                 f"local server."
                 ) if billing else
                (f"The selected provider ({provider}) authenticates, and no "
                 f"API key is set.\n\n"
                 f"Enter one in the provider settings, or switch to a local "
                 f"model, which needs no key.")
            ),
        )
    normalised = (model or "").strip()
    if not normalised:
        return Readiness(
            code=NO_MODEL, can_run=False, label="No model set",
            detail=(
                f"The {stage} model field is empty or contains only "
                f"whitespace.\n\n"
                f"Type the name of the model to screen with. A run started "
                f"without one would call nothing, return no answers, and "
                f"still report every record as processed."
            ),
        )
    # Wave 11 session B. "Ready" must mean **reachable**, not merely
    # configured — a configured provider whose server is not answering
    # produces a run that fails record by record, which the run report
    # would then have to explain after the fact.
    #
    # No probe is performed here: it is a network call, and this function
    # is called from Tk callbacks. It is *told* the result. Being told
    # nothing is its own state rather than silent optimism, because "we
    # have not looked" and "we looked and it answered" are different
    # claims and only the second licenses a run.
    if probe is None:
        return Readiness(
            code=NOT_CHECKED, can_run=False, label="Checking…",
            detail=(
                f"metaScreener has not yet confirmed that the {stage} "
                f"provider is reachable. This resolves on its own; if it "
                f"does not, re-check the provider settings."
            ),
            model=normalised,
        )

    state = getattr(probe, "state", None)
    if state == "no_models":
        return Readiness(
            code=NO_MODELS_PULLED, can_run=False, label="No models pulled",
            detail=getattr(probe, "detail", "") or
            "The server is running but has no models pulled yet.",
            model=normalised,
        )
    if state != "ready":
        # The detail is carried through verbatim. D4/D5 turn on three
        # distinct, actionable messages — not installed, installed but
        # stopped, and reachable but empty are three different problems —
        # and flattening them into one "unavailable" is exactly the wasted
        # afternoon those decisions exist to prevent.
        return Readiness(
            code=ENDPOINT_UNREACHABLE, can_run=False,
            label="Unreachable",
            detail=getattr(probe, "detail", "") or
            "The configured endpoint did not answer.",
            model=normalised,
        )

    return Readiness(code=READY, can_run=True, label="Ready to run",
                     detail="", model=normalised)


# ----------------------------
# Controls — which buttons are live
# ----------------------------

@dataclass(frozen=True)
class ControlStates:
    """Enabled/disabled for the five buttons every LLM stage carries.

    IL's sixth button, "Export ScreenA_Report.xlsx…", follows the same rule
    as ``export`` and reads it rather than getting a field of its own: a
    field that is always equal to another field is the two-representations
    -of-one-fact shape this project keeps being bitten by (F-69, F-131).
    """

    run: bool
    cancel: bool
    export: bool
    export_errors: bool
    export_bundle: bool


def control_states(*, running: bool, readiness: "Readiness", has_rows: bool,
                   has_input_errors: bool) -> ControlStates:
    """Decide every button's state, in one place, from the readiness the
    rest of the stage already agrees on.

    F-118. ``_set_controls_running`` used to re-enable the Run button on
    ``self.bundle_zip_path`` **alone**, while ``_load_bundle_inputs`` set it
    from ``_has_openai_key()`` alone. Two functions, two disjoint inputs,
    one button — and because ``_set_controls_running(False)`` runs in the
    ``finally`` of every run, the one that ignores readiness ran *last*. So
    the gate the load path applied survived exactly until the first run of a
    session finished, after which the Run button was live regardless.

    Taking a ``Readiness`` rather than a bundle flag is what makes the
    second predicate impossible to reintroduce: there is nowhere left to put
    a different one.
    """
    return ControlStates(
        run=(not running) and readiness.can_run,
        cancel=running,
        export=(not running) and has_rows,
        export_errors=(not running) and has_input_errors,
        export_bundle=(not running) and has_rows,
    )


# ----------------------------
# Numeric settings
# ----------------------------

@dataclass(frozen=True)
class NumericSettings:
    """The two numeric knobs, corrected, with what was wrong about them."""

    batch_size: int
    trunc_chars: int
    problems: Tuple[str, ...] = ()


def parse_numeric_settings(*, batch_raw: Any, trunc_raw: Any,
                           batch_default: int,
                           trunc_default: int) -> NumericSettings:
    """Read the two numeric settings, correct what cannot be used, and say
    what was corrected.

    F-118. Both are free-text entries guarded only by
    ``try: int(...) except: <default>``, which rescues ``"abc"`` and
    cheerfully accepts ``"-100"``.

    **A negative ``trunc_chars`` is the live defect, and it is worse than
    the row states.** It reaches the prompt builder's
    ``if trunc_chars and len(s) > trunc_chars`` guard, where it is truthy
    and the comparison is unconditionally true, so ``s[:trunc_chars]`` runs
    as a *negative slice*. Measured on the real builder with ``-100``: the
    last 100 characters are cut from the abstract, **and the title and
    keywords are emptied outright**, because any field shorter than 100
    characters slices to ``""``. Titles and keywords are routinely under
    100 characters, so a modest negative value blanks two of the three
    fields for essentially every record. Nothing logs it; ``valid_quote``
    collapses because there is no text left to validate a quote against;
    and the wave-8 run report scores the records as ``answered``, because
    the model did answer — about nothing.

    ``0`` is left alone. The builder's guard is ``if trunc_chars and …``,
    so falsy means "do not truncate" — a documented value, not an error.

    ``batch_size`` below 1 is clamped and reported but was never silently
    *wrong*: ``plugins/_common/llm_client.py::chunked`` does
    ``max(1, int(n))`` and its caller does it again, so 0 degrades to
    one-item batches. It is reported because what the user typed and what
    ran differed, which is the same complaint one level down.

    Correcting-and-reporting rather than refusing: a typo in a numeric box
    should not throw away a configured run, and the existing behaviour
    already substitutes a default for non-numeric input. What changes is
    that the substitution stops being silent.
    """
    problems: List[str] = []

    def _as_int(raw: Any) -> Optional[int]:
        try:
            return int(str(raw).strip())
        except Exception:
            return None

    batch = _as_int(batch_raw)
    if batch is None:
        problems.append(
            f"Batch size {str(batch_raw)!r} is not a whole number; "
            f"using {batch_default}.")
        batch = batch_default
    elif batch < 1:
        problems.append(
            f"Batch size {batch} is below 1; using 1. The engine clamps this "
            f"anyway, so the run would have used one-item batches whatever "
            f"the box said.")
        batch = 1

    trunc = _as_int(trunc_raw)
    if trunc is None:
        problems.append(
            f"Truncation {str(trunc_raw)!r} is not a whole number; "
            f"using {trunc_default}.")
        trunc = trunc_default
    elif trunc < 0:
        problems.append(
            f"Truncation {trunc} is negative; using {trunc_default}. A "
            f"negative value does not shorten a field, it removes the last "
            f"{abs(trunc)} characters of it — and empties any field shorter "
            f"than that, which for most records is the title and the "
            f"keywords.")
        trunc = trunc_default

    return NumericSettings(batch_size=batch, trunc_chars=trunc,
                           problems=tuple(problems))


# ----------------------------
# Batch size — D6
# ----------------------------

#: What a keyless (i.e. local) provider gets when nobody has chosen.
#:
#: The coordinator's range is 5–10 and this is the bottom of it,
#: deliberately. The two costs of a smaller batch are more requests and
#: more wall-clock, and against a local server both are free — there is no
#: per-request charge and the machine is the user's own. The benefit is a
#: shorter list for the model to keep track of. When one side of a
#: trade-off costs nothing, taking the safer end of the stated range is
#: not a judgement call.
#:
#: It also happens to be the value the committed goldens were captured at
#: (`_invocation: {'batch_size': 5, …}`), which is a coincidence rather
#: than a reason: the goldens are replayed with an explicit batch size and
#: nothing here reaches them.
LOCAL_BATCH_SIZE = 5

#: The range the coordinator specified, kept as data so the constant above
#: cannot drift outside it without a test noticing.
LOCAL_BATCH_RANGE = (5, 10)


def recommended_batch_size(provider: str,
                           endpoint: Optional[str] = None) -> Optional[int]:
    """The batch size to suggest for this configuration, or ``None``.

    ``None`` means *no suggestion* — the stage's own module default
    answers, which for EL and IL is 50. Only a configuration this
    application knows to be a small local model gets a number.

    **Asked about the resolved pair, after session C's review.** The
    first version asked the provider name alone, on the reasoning that
    getting the key gate wrong spends money while getting the batch size
    wrong only costs a slower run. That reasoning was wrong about the
    cost: the criterion and the system prompt are re-sent with **every**
    batch, so ten times the batches is roughly ten times those tokens —
    and against the paid vendor that is a bill, not a wait. A stage whose
    provider says ``local`` and whose endpoint override points at
    api.openai.com would have run at 5.

    For an ambiguous *keyless* endpoint the earlier reasoning still
    holds: a ``custom`` endpoint may be a large hosted model or
    llama.cpp on a laptop, and 5 is the reading that works for both.
    """
    if key_required_for(provider, endpoint):
        return None
    return LOCAL_BATCH_SIZE


def batch_size_tooltip(provider: str,
                       endpoint: Optional[str] = None) -> str:
    """Why this number is what it is — beside the number.

    **Three things this wording must not do**, each of which would be
    false reassurance rather than an explanation:

    1. **It must not read as a safety measure.** Batch size is a
       *quality* knob. The correctness defect in this neighbourhood was
       F-86 — a response naming a record from another batch, whose quote
       then validated against *that* record's text — and it is closed, in
       the engine, since wave 7. It also fired at ``batch_size = 1``,
       because the acceptance guard admitted any known ``a_id`` whatever
       batch it came from. So nothing here may suggest that a smaller
       batch makes a run *safer*: it does not, and a user who believed it
       would be trusting the wrong thing.
    2. **It must not imply the cache is affected.** F-101: the cache key
       hashes a synthetic **one-item** prompt, so ``batch_size`` is
       invisible to it. Entries produced at 50 are served to a run at 5
       and the other way round. That is exactly what a user needs to know
       before touching this box — otherwise the reasonable fear "will
       this throw away my cached decisions?" stops them changing it.
    3. **It must not claim anything about how well a local model
       screens.** That needs a live measurement and belongs to wave 12.
       The claim here is narrow and defensible: asking for fewer JSON
       objects per reply is easier for a small model to keep track of.
    """
    suggested = recommended_batch_size(provider, endpoint)
    lead = (
        "How many records go into one request.\n\n"
        "Each request asks the model for one JSON object per record in a "
        "single reply, so a batch of 50 asks for fifty at once."
    )

    if suggested is not None:
        why = (
            f"\n\nThis drops to {suggested} for a local model. Small models "
            f"lose track of a long list well before fifty and start "
            f"returning fewer objects than they were given. Raise it if "
            f"yours keeps up — against a server on this machine the only "
            f"cost of a small batch is more requests, and those are free."
        )
    else:
        why = (
            "\n\nA hosted model of this class generally keeps track of a "
            "fifty-item list. This drops to "
            f"{LOCAL_BATCH_SIZE} when a local provider is selected."
        )

    honesty = (
        "\n\nThis is a QUALITY setting, not a correctness one. A smaller "
        "batch does not make a run safer: the cross-batch substitution "
        "defect (F-86) fired at a batch size of 1 as readily as at 50, and "
        "it is closed in the engine rather than by this number."
    )

    cache = (
        "\n\nChanging it does not invalidate your cache. The cache key is "
        "computed from a one-record prompt (F-101), so the batch size is "
        "invisible to it and cached decisions are reused whatever this "
        "box says."
    )

    return lead + why + honesty + cache


def tk_state(enabled: bool) -> str:
    """``True``/``False`` to the two strings ``configure(state=…)`` wants.

    This is Tk *vocabulary*, not Tk: it imports nothing and takes no widget.
    It lives here so the Views' only remaining job is to read widgets, call
    one of these functions, and write widgets — which is the property that
    makes the decisions testable.
    """
    return "normal" if enabled else "disabled"
