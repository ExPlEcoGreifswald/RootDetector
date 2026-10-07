"""Shared job cancellation and diagnostic helpers."""

import threading
import typing as tp
import uuid


class OperationCancelled(RuntimeError):
    """Raised when a cooperative processing operation is cancelled."""


def new_diagnostic_id() -> str:
    """Return a short correlation ID suitable for UI and log messages."""
    return uuid.uuid4().hex[:12]


def cancellation_event(settings:tp.Any) -> tp.Optional[threading.Event]:
    event = getattr(settings, 'cancel_event', None)
    return event if isinstance(event, threading.Event) else None


def raise_if_cancelled(
    settings:tp.Any=None,
    event:tp.Optional[threading.Event]=None,
) -> None:
    event = event or cancellation_event(settings)
    if event is not None and event.is_set():
        raise OperationCancelled('Cancellation was requested.')


def error_payload(
    code:str,
    message:str,
    stage:str,
    item_id:tp.Optional[str]=None,
    retryable:bool=True,
    error_type:tp.Optional[str]=None,
) -> tp.Dict[str, tp.Any]:
    payload = {
        'code': code,
        'message': message,
        'stage': stage,
        'retryable': retryable,
        'diagnostic_id': new_diagnostic_id(),
    }
    if item_id is not None:
        payload['item_id'] = item_id
    if error_type is not None:
        payload['type'] = error_type
    return payload
