"""Receipt Scanner — multimodal OCR (decoupled from the Agent A invoice flow).

  POST /receipts/scan — OCR a receipt image and suggest an expense category.
"""
from __future__ import annotations

import base64
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from langchain_core.messages import HumanMessage

from src.domains.identity.dependencies import RequireIntelligenceRead
from src.domains.intelligence.orchestrator import build_receipt_graph
from src.domains.intelligence.schemas import ReceiptExtraction, ReceiptScanResponse

router = APIRouter()

# Receipt upload limits — mirror the nginx client_max_body_size and the
# frontend's accepted-types list so rejections are consistent across layers.
_RECEIPT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_RECEIPT_ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}


@router.post("/receipts/scan", response_model=ReceiptScanResponse)
async def scan_receipt(
    current_user: RequireIntelligenceRead,
    file: Annotated[UploadFile, File()],
) -> ReceiptScanResponse:
    """
    OCR a receipt image and suggest an expense category.

    Pipeline (LangGraph): receipt_ocr → receipt_classifier.  This endpoint does
    NOT persist anything — it returns the extracted fields for the user to
    review/edit, after which the frontend posts the confirmed values to
    ``POST /api/v1/finance/receipts`` to create the expense.

    Validation: the upload must be an allowed image/PDF MIME type and under
    10 MB.  On a Gemini failure the graph degrades to an empty extraction plus
    an ``error`` message so the user can still fill the form by hand.
    """
    if file.content_type not in _RECEIPT_ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{file.content_type}'. "
                "Upload a JPG, PNG, WEBP, GIF, or PDF receipt."
            ),
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(image_bytes) > _RECEIPT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Receipt image must be under 10 MB.",
        )

    session_id = str(uuid.uuid4())
    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content="Scan receipt")],
        "next": "receipt_ocr",
        "context": {
            "image_bytes_b64": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": file.content_type,
        },
        "session_id": session_id,
        "user_id": str(current_user.id),
        "mode": "insights",
    }

    graph = build_receipt_graph()
    final_state = await graph.ainvoke(initial_state)
    context = final_state.get("context", {})

    raw_extraction = context.get("receipt_extraction") or {}
    errors = final_state.get("error_messages") or []

    return ReceiptScanResponse(
        session_id=session_id,
        extraction=ReceiptExtraction.model_validate(raw_extraction),
        suggested_category=context.get("suggested_category", "other"),
        error=errors[0] if errors else None,
    )
