def public_document_status(status: str) -> str:
    """Normalize legacy worker status values for API responses."""
    if status == "error":
        return "failed"
    return status
