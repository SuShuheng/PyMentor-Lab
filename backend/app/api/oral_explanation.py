"""Student-facing oral explanation scoring endpoint (BE-026).

Composes BE-022 (TTS prompt synthesis) + BE-025 (ASR capture) + an LLM rubric
to score a student's verbal explanation of a concept. The flow is:

1. Synthesize the TTS prompt clip (mock → silent WAV + subtitle track).
2. Accept the student's recorded audio explanation and transcribe it (mock →
   deterministic stub).
3. Score the transcript with a deterministic mock rubric (length + keyword
   coverage). Live LLM scoring is INT-010 NOT-RUN.
4. Record ``ORAL_EXPLANATION_SCORED`` evidence and project it to the
   ``INDEPENDENCE_SUPPORT`` profile dimension at low confidence (design §8.3:
   oral explanations are an independence/explanation signal).

The endpoint NEVER advances mastery — that decision is owned exclusively by the
assessment pipeline (CONTRACT rule). Mock mode is the only branch exercised by
CI; ``mock: True`` always surfaces in the response so a placeholder result is
never confused for a live one.

Degradation contract: when a live render/transcription is requested but the
upstream fails (INT-010 NOT-RUN for the live branch), the endpoint surfaces a
typed ``PROVIDER_UNAVAILABLE`` (HTTP 503) envelope so the notebook degrades
cleanly. Shape parity with BE-022 / BE-024 / BE-025.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.command_idempotency import begin_command, scope_for_request
from app.config import get_settings
from app.contracts.oral import (
    ORAL_ALLOWED_MIME_TYPES,
    ORAL_MAX_AUDIO_BYTES,
    ORAL_MAX_DURATION_MS,
    ORAL_MAX_PROMPT_CHARS,
    OralExplanationResponse,
    OralRubricItem,
    OralTranscriptStage,
    OralTTSStage,
)
from app.db import get_db
from app.evidence import record_audit, record_evidence
from app.idempotency import save_response
from app.models import ProfileDimension, User
from app.models.base import RoleName
from app.object_store import MinioObjectStore, MinioObjectStoreSettings
from app.observability import record_provider_call
from app.profile_projection import DimensionUpdate, project_profile
from app.provider_adapters import ProviderAdapterError
from app.providers import (
    ProviderSecretError,
    ProviderType,
    ResolvedProvider,
    decode_provider_master_key,
    resolve_enabled_provider,
)
from app.rbac import get_current_user
from app.services import get_user_roles
from app.uow import SqlAlchemyUnitOfWork

router = APIRouter(prefix="/api/v1/oral-explanation", tags=["oral-explanation"])

#: Event type recorded for every scored oral explanation (design §8.3).
ORAL_EXPLANATION_EVENT_TYPE = "ORAL_EXPLANATION_SCORED"

#: Low confidence anchor for oral-explanation evidence. Self-reported-style
#: signals never dominate real assessment evidence (mirrors BE-018 onboarding).
_ORAL_EVIDENCE_CONFIDENCE = 0.3

#: Deterministic mock LLM rubric anchor — a short canonical answer used both as
#: the ``model_answer`` field and as the keyword source for the mock scorer. In
#: live mode this would come from the governed course content + LLM.
_MOCK_MODEL_ANSWER = (
    "Python 的 for 循环通过迭代可迭代对象（如列表、字符串、range）依次取出每个元素，"
    "在循环体内执行操作，直到序列结束。可结合 range() 控制次数，使用 break/continue "
    "控制流向。"
)

#: Keywords the mock rubric looks for to reward coverage. Coarse on purpose —
#: it only governs the deterministic placeholder score.
_MOCK_KEYWORDS = ("循环", "迭代", "序列", "range", "元素", "break", "continue")


# ---------------------------------------------------------------------------
# Dependency-injected adapter factories (mirrors BE-022 / BE-025)
# ---------------------------------------------------------------------------


def _master_key() -> bytes:
    try:
        return decode_provider_master_key(get_settings().provider_master_key)
    except ProviderSecretError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider credential service is unavailable",
        ) from error


def get_tts_adapter_builder() -> Any:
    """Return the TTS adapter factory.

    Returning the factory itself (rather than depending on ``build_tts_adapter``
    directly) keeps FastAPI from introspecting the factory's ``provider``
    argument as a query parameter. Tests override this dependency to inject a
    failing adapter for the degraded-path assertions.
    """

    from app.provider_adapters.tts_xunfei import build_tts_adapter

    return build_tts_adapter


def get_asr_adapter_builder() -> Any:
    """Return the ASR adapter factory (same rationale as the TTS one)."""

    from app.provider_adapters.asr_xunfei import build_asr_adapter

    return build_asr_adapter


def build_oral_object_store() -> MinioObjectStore:
    """Construct the MinIO object store for the synthesized TTS prompt clip.

    Exposed as a FastAPI-style factory so tests override it with an in-memory
    fake without monkeypatching module internals (mirrors BE-022).
    """

    return MinioObjectStore(MinioObjectStoreSettings.from_application_settings(get_settings()))


# ---------------------------------------------------------------------------
# Upload validation (shared shape with BE-025 ASR)
# ---------------------------------------------------------------------------


def _normalize_mime(content_type: str | None, filename: str | None) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if not mime and filename:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        mime = {
            "wav": "audio/wav",
            "webm": "audio/webm",
            "ogg": "audio/ogg",
            "oga": "audio/ogg",
            "mp3": "audio/mpeg",
            "mpga": "audio/mpeg",
            "mp2": "audio/mpeg",
        }.get(suffix, "")
    return mime


def _read_and_validate(file: UploadFile) -> tuple[bytes, str]:
    """Read the upload once, enforcing the MIME allowlist and size cap."""

    mime = _normalize_mime(file.content_type, file.filename)
    if mime not in ORAL_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(f"unsupported audio type: must be one of {sorted(ORAL_ALLOWED_MIME_TYPES)}"),
        )
    audio_bytes = file.file.read(ORAL_MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) > ORAL_MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"audio exceeds the {ORAL_MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit"),
        )
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="uploaded audio is empty",
        )
    return audio_bytes, mime


# ---------------------------------------------------------------------------
# TTS prompt clip persistence (reuses BE-022 governed prefix)
# ---------------------------------------------------------------------------


def _object_key(*, tenant_id: UUID, user_id: UUID, request_id: UUID) -> str:
    return f"resources/oral/{tenant_id}/{user_id}/{request_id}/v1"


def _persist_prompt_audio(
    object_store: MinioObjectStore,
    *,
    tenant_id: UUID,
    user_id: UUID,
    request_id: UUID,
    audio_bytes: bytes,
    mime: str,
) -> tuple[str, str]:
    key = _object_key(tenant_id=tenant_id, user_id=user_id, request_id=request_id)
    stored = object_store.put(
        key=key,
        content=audio_bytes,
        mime_type=mime,
        version=1,
    )
    return stored.key, stored.digest


def _audio_url(*, request_id: UUID, digest: str) -> str:
    return f"/api/v1/oral-explanation/prompt/{request_id}/{digest}"


# ---------------------------------------------------------------------------
# Mock LLM rubric — deterministic scoring on transcript length + keywords
# ---------------------------------------------------------------------------


def _score_transcript(transcript: str) -> tuple[float, list[OralRubricItem]]:
    """Deterministic mock rubric over ``transcript``.

    Length band contributes a fluency score; keyword coverage contributes a
    content-correctness score. The aggregate is a bounded mean so the result
    stays in [0, 1]. Live LLM scoring is INT-010 NOT-RUN; this stub never
    inspects provider state and is safe to call directly in tests.
    """

    text = (transcript or "").strip()
    length = len(text)
    # Fluency: 0 below 8 chars, ramping to 1.0 at ~120 chars.
    fluency = max(0.0, min(1.0, (length - 8) / max(112, 1))) if length > 8 else 0.0
    hits = sum(1 for kw in _MOCK_KEYWORDS if kw in text)
    coverage = min(1.0, hits / 3.0)
    # Structure: reward a couple of punctuation cues (coherent sentences).
    structure = min(1.0, sum(1 for ch in text if ch in "。，、；！？") / 3.0)
    rubric = [
        OralRubricItem(
            criterion="fluency",
            score=round(fluency, 3),
            feedback="mock scorer: transcript length band.",
        ),
        OralRubricItem(
            criterion="content_coverage",
            score=round(coverage, 3),
            feedback=f"mock scorer: {hits}/{len(_MOCK_KEYWORDS)} key concepts mentioned.",
        ),
        OralRubricItem(
            criterion="structure",
            score=round(structure, 3),
            feedback="mock scorer: sentence punctuation cues.",
        ),
    ]
    aggregate = round((fluency + coverage + structure) / 3.0, 3)
    return aggregate, rubric


# ---------------------------------------------------------------------------
# Role guard (mirrors BE-018 onboarding — oral explanation is student-only)
# ---------------------------------------------------------------------------


def _require_student_role(db: Session, user: User) -> None:
    if RoleName.STUDENT.value not in set(get_user_roles(db, user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="student role required",
        )


# ---------------------------------------------------------------------------
# Provider-call audit + observability (mirrors BE-022 / BE-025)
# ---------------------------------------------------------------------------


def _record_stage_outcome(
    db: Session,
    *,
    user: User,
    provider: ResolvedProvider | None,
    provider_type: ProviderType,
    operation: str,
    action: str,
    trace_id: str,
    ok: bool,
    error_code: str | None,
    extra_detail: dict[str, Any] | None = None,
) -> None:
    record_audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        resource_type="oral_explanation",
        resource_id=trace_id,
        trace_id=trace_id,
        detail={
            "provider_mode": "MOCK" if provider is None else "LIVE",
            "error_code": error_code,
            **(extra_detail or {}),
        },
    )
    record_provider_call(
        db,
        tenant_id=user.tenant_id,
        provider_type=provider_type,
        vendor=(provider.vendor if provider is not None else "mock"),
        model=(provider.model if provider is not None else f"mock-{provider_type.value.lower()}"),
        operation=operation,
        outcome="SUCCEEDED" if ok else "FAILED",
        latency_ms=0,
        rate_limited=False,
        trace_id=trace_id,
        provider_config_id=(provider.id if provider is not None else None),
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("", response_model=OralExplanationResponse)
async def score_oral_explanation(
    request: Request,
    node_id: UUID = Form(...),
    prompt_text: str = Form(...),
    expected_profile_version: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    tts_adapter_factory: Any = Depends(get_tts_adapter_builder),
    asr_adapter_factory: Any = Depends(get_asr_adapter_builder),
    object_store: MinioObjectStore = Depends(build_oral_object_store),
) -> JSONResponse:
    """Score a student's verbal explanation (mock composition by default).

    Student-only, tenant-scoped, idempotent under ``Idempotency-Key``. The
    result is recorded as ``ORAL_EXPLANATION_SCORED`` evidence and projected to
    ``INDEPENDENCE_SUPPORT`` at low confidence; mastery is NEVER touched.
    """

    _require_student_role(db, user)
    if not 1 <= len(prompt_text) <= ORAL_MAX_PROMPT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"prompt_text must be 1..{ORAL_MAX_PROMPT_CHARS} characters",
        )

    scope = scope_for_request(request, tenant_id=user.tenant_id, user_id=user.id)
    cached = begin_command(db, scope)
    if cached is not None and cached.response_status is not None:
        return JSONResponse(content=cached.response_body or {}, status_code=cached.response_status)

    audio_bytes, mime = _read_and_validate(file)
    trace_id = str(request.state.trace_id)

    # Resolve providers (None ⇒ mock mode, the only branch CI exercises).
    tts_provider = resolve_enabled_provider(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.TTS,
        master_key=_master_key(),
    )
    asr_provider = resolve_enabled_provider(
        db,
        tenant_id=user.tenant_id,
        provider_type=ProviderType.ASR,
        master_key=_master_key(),
    )
    tts_adapter = tts_adapter_factory(tts_provider)
    asr_adapter = asr_adapter_factory(asr_provider)

    # ---- Stage 1: TTS prompt synthesis (mock → silent WAV) -----------------
    try:
        tts_result = tts_adapter.generate(prompt_text, {"voice": "xiaoyan"})
    except ProviderAdapterError as error:
        _record_stage_outcome(
            db,
            user=user,
            provider=tts_provider,
            provider_type=ProviderType.TTS,
            operation="ORAL_TTS_PROMPT",
            action="ORAL_TTS_FAILED",
            trace_id=trace_id,
            ok=False,
            error_code="PROVIDER_FAILED",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS provider is unavailable",
        ) from error
    _record_stage_outcome(
        db,
        user=user,
        provider=tts_provider,
        provider_type=ProviderType.TTS,
        operation="ORAL_TTS_PROMPT",
        action="ORAL_TTS_GENERATED",
        trace_id=trace_id,
        ok=True,
        error_code=None,
        extra_detail={"duration_ms": tts_result.duration_ms, "mock": tts_result.mock},
    )

    # Persist the prompt clip so the renderer can fetch it (governed prefix).
    request_id = uuid4()
    _object_key_str, digest = _persist_prompt_audio(
        object_store,
        tenant_id=user.tenant_id,
        user_id=user.id,
        request_id=request_id,
        audio_bytes=tts_result.audio_bytes,
        mime=tts_result.mime,
    )

    # ---- Stage 2: ASR transcription of the student's explanation -----------
    try:
        asr_result = asr_adapter.transcribe(audio_bytes, mime)
    except ProviderAdapterError as error:
        _record_stage_outcome(
            db,
            user=user,
            provider=asr_provider,
            provider_type=ProviderType.ASR,
            operation="ORAL_ASR_TRANSCRIBE",
            action="ORAL_ASR_FAILED",
            trace_id=trace_id,
            ok=False,
            error_code="PROVIDER_FAILED",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ASR provider is unavailable",
        ) from error
    if asr_result.duration_ms > ORAL_MAX_DURATION_MS:
        _record_stage_outcome(
            db,
            user=user,
            provider=asr_provider,
            provider_type=ProviderType.ASR,
            operation="ORAL_ASR_TRANSCRIBE",
            action="ORAL_ASR_FAILED",
            trace_id=trace_id,
            ok=False,
            error_code="DURATION_LIMIT",
            extra_detail={"duration_ms": asr_result.duration_ms},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(f"audio duration exceeds the {ORAL_MAX_DURATION_MS // 1000}s limit"),
        )
    _record_stage_outcome(
        db,
        user=user,
        provider=asr_provider,
        provider_type=ProviderType.ASR,
        operation="ORAL_ASR_TRANSCRIBE",
        action="ORAL_ASR_TRANSCRIBED",
        trace_id=trace_id,
        ok=True,
        error_code=None,
        extra_detail={
            "duration_ms": asr_result.duration_ms,
            "size_bytes": len(audio_bytes),
        },
    )

    # ---- Stage 3: mock LLM rubric over the transcript ----------------------
    score, rubric = _score_transcript(asr_result.transcript)

    # ---- Stage 4: record evidence + project to INDEPENDENCE_SUPPORT --------
    # Oral explanations are an independence/explanation signal (design §8.3):
    # they support the profile at low confidence and NEVER advance mastery.
    evidence_event_id = f"evt_oral_{uuid4().hex}"
    response_mock = bool(tts_result.mock) or (asr_result.provider_mode == "MOCK")
    payload: dict[str, Any] = {
        "node_id": str(node_id),
        "score": score,
        "rubric": [item.model_dump(mode="json") for item in rubric],
        "transcript": asr_result.transcript,
        "duration_ms": asr_result.duration_ms,
        "prompt_duration_ms": tts_result.duration_ms,
        "mock": response_mock,
    }

    with SqlAlchemyUnitOfWork(accept_session=db) as uow:
        evidence = record_evidence(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            event_id=evidence_event_id,
            event_type=ORAL_EXPLANATION_EVENT_TYPE,
            trace_id=trace_id,
            node_id=node_id,
            payload=payload,
            evidence_confidence=_ORAL_EVIDENCE_CONFIDENCE,
        )
        if evidence is None:
            # The idempotency-key reservation already prevents duplicate
            # event_ids; a collision here is a contract violation, not a retry.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="oral explanation evidence already recorded",
            )
        # Project the signal to INDEPENDENCE_SUPPORT at low confidence. The
        # score maps directly: higher explanation score ⇒ more independence.
        project_profile(
            db,
            tenant_id=user.tenant_id,
            student_id=user.id,
            source_event_id=evidence_event_id,
            expected_version=expected_profile_version,
            updates=[
                DimensionUpdate(
                    dimension=ProfileDimension.INDEPENDENCE_SUPPORT.value,
                    scope_key=f"oral:{node_id}",
                    score=score,
                    confidence=_ORAL_EVIDENCE_CONFIDENCE,
                    support_level=_support_level_for(score),
                )
            ],
        )
        uow.publish(
            event_type=ORAL_EXPLANATION_EVENT_TYPE,
            aggregate_type="oral_explanation",
            aggregate_id=evidence_event_id,
            tenant_id=user.tenant_id,
            trace_id=trace_id,
            payload={
                "student_id": str(user.id),
                "node_id": str(node_id),
                "score": score,
                "mock": response_mock,
            },
        )
        response_body = OralExplanationResponse(
            prompt=OralTTSStage(
                audio_url=_audio_url(request_id=request_id, digest=digest),
                mime=tts_result.mime,
                duration_ms=tts_result.duration_ms,
                mock=tts_result.mock,
            ),
            transcript=OralTranscriptStage(
                text=asr_result.transcript,
                duration_ms=asr_result.duration_ms,
                confidence=asr_result.confidence,
                language=asr_result.language,
                provider_mode=asr_result.provider_mode,
            ),
            rubric=rubric,
            score=score,
            model_answer=_MOCK_MODEL_ANSWER,
            evidence_id=evidence_event_id,
            mock=response_mock,
        ).model_dump(mode="json")
        save_response(
            db,
            key=scope.key,
            response_status=status.HTTP_200_OK,
            response_body=response_body,
        )
        uow.commit()

    # Raw audio is purged here — nothing in this path persists it.
    del audio_bytes
    return JSONResponse(content=response_body, status_code=status.HTTP_200_OK)


def _support_level_for(score: float) -> int:
    """Map an aggregate explanation score to a coarse support_level hint.

    Higher score ⇒ lower support_level (more independent). Bounded to [0, 3]
    per the profile contract; this hint is easily overridden by stronger
    assessment evidence.
    """

    if score >= 0.75:
        return 0
    if score >= 0.5:
        return 1
    if score >= 0.25:
        return 2
    return 3


__all__ = [
    "build_oral_object_store",
    "get_asr_adapter_builder",
    "get_tts_adapter_builder",
    "router",
]
