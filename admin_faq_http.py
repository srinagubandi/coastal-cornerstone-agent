"""
HTTP handlers for /private/api/dashboard/faq-review.

These handlers assume that authentication and CSRF checks have already been
performed by the outer wrapper. The session dict must contain at least 'role'
('admin' or 'ben') and 'csrf' token.
"""
import re
from urllib.parse import urlsplit

from dashboard import verify_password
from config import ADMIN_EMAIL, RECIPIENT
from faq_review import Conflict

HEX32 = re.compile(r'^[0-9a-f]{32}$')


def _actor(session):
    """Return the actor email for the current session."""
    role = session.get('role', 'ben')
    if role == 'admin':
        return ADMIN_EMAIL
    return RECIPIENT


def _password_ok(handler, session, body, client):
    """Verify the password for step-up actions.  Returns True and strips the
    password from *body* on success; sends 403/429/503 and returns False on failure."""
    password = body.pop('password', '')
    if not isinstance(password, str) or not password:
        handler.respond(403, {'error': 'Invalid password'})
        return False
    s = handler.service
    # Rate limit password attempts
    ok, retry = s.store.rate(client, 'login')
    if not ok:
        handler.respond(429, {'error': 'Rate limit exceeded'}, extra={'Retry-After': str(retry)})
        return False
    # Acquire hash slot to prevent concurrent DoS
    slot_acquired = s.dashboard.hash_slots.acquire(blocking=False)
    if not slot_acquired:
        handler.respond(503, {'error': 'Server busy, try again'})
        return False
    try:
        if session.get('role') == 'admin':
            encoded = s.config.admin_hash
        else:
            encoded = s.config.ben_admin_hash
        if not verify_password(password, encoded):
            handler.respond(403, {'error': 'Invalid password'})
            return False
        return True
    finally:
        if slot_acquired:
            s.dashboard.hash_slots.release()


def _reject_query(handler):
    """Reject requests that contain a query string."""
    if urlsplit(handler.path).query:
        handler.respond(400, {'error': 'Query parameters are not allowed'})
        return True
    return False


def _handle_exception(handler, exc):
    """Map known exceptions to HTTP error responses."""
    if isinstance(exc, ValueError):
        handler.respond(400, {'error': str(exc)})
    elif isinstance(exc, Conflict):
        handler.respond(409, {'error': str(exc)})
    else:
        # Avoid leaking internal details.
        handler.respond(500, {'error': 'Internal server error'})
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def handle_get(handler, path, session):
    """Handle GET requests under /private/api/dashboard/faq-review."""
    if not session:
        handler.respond(401, {'error': 'Unauthorized'})
        return True
    if session.get('role') not in ('admin', 'ben'):
        handler.respond(401, {'error': 'Unauthorized'})
        return True
    if _reject_query(handler):
        return True

    s = handler.service
    review = s.faq_review
    agent = s.agent
    chat = s.chat

    # /drafts
    if path == '/drafts':
        try:
            items = review.list_drafts()
            published = agent.public_faq()
            releases = review.release_list() if hasattr(review, 'release_list') else []
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, {
            'items': items,
            'published': published,
            'releases': releases,
        })
        return True

    # /drafts/{32hex}
    match = re.match(r'^/drafts/([0-9a-f]{32})$', path)
    if match:
        draft_id = match.group(1)
        try:
            detail = review.detail(draft_id)
        except Exception as exc:
            return _handle_exception(handler, exc)
        if detail is None:
            handler.respond(404, {'error': 'Draft not found'})
        else:
            handler.respond(200, detail)
        return True

    # /audit
    if path == '/audit':
        try:
            metadata = review.audit_list()
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, {'items': metadata})
        return True

    # /review-queue
    if path == '/review-queue':
        try:
            queue = review.review_queue()
        except Exception as exc:
            return _handle_exception(handler, exc)
        if isinstance(queue, list):
            handler.respond(200, {'count': len(queue), 'items': queue})
        else:
            handler.respond(200, queue)
        return True

    # Unknown GET path
    handler.respond(404, {'error': 'Not found'})
    return True


def handle_post(handler, path, body, session, client):
    """Handle POST requests under /private/api/dashboard/faq-review."""
    if not session:
        handler.respond(401, {'error': 'Unauthorized'})
        return True
    if session.get('role') not in ('admin', 'ben'):
        handler.respond(401, {'error': 'Unauthorized'})
        return True
    if _reject_query(handler):
        return True
    if not isinstance(body, dict):
        handler.respond(400, {'error': 'Body must be a JSON object'})
        return True

    s = handler.service
    review = s.faq_review
    chat = s.chat
    actor = _actor(session)

    # /drafts/{id}/save
    match = re.match(r'^/drafts/([0-9a-f]{32})/save$', path)
    if match:
        draft_id = match.group(1)
        allowed = {'revision', 'question', 'answer', 'source_urls', 'tags', 'state'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        if body.get('state') == 'published':
            handler.respond(400, {'error': 'Cannot set state to published directly'})
            return True
        try:
            review.save(draft_id, body, actor)
            updated = review.detail(draft_id)
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, updated)
        return True

    # /entries/{int}/review
    match = re.match(r'^/entries/(\d+)/review$', path)
    if match:
        entry_id = int(match.group(1))
        allowed = {'classification', 'revision'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        classification = body.get('classification')
        revision = body.get('revision')
        try:
            chat.update_entry(entry_id, classification, revision, actor)
            # Return updated entry so revision is visible
            entry = chat.get_entry(entry_id)
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, entry)
        return True

    # /entries/{int}/promote
    match = re.match(r'^/entries/(\d+)/promote$', path)
    if match:
        entry_id = int(match.group(1))
        allowed = {'revision', 'question', 'source_urls'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        try:
            entry = chat.get_entry(entry_id)
            result = review.promote(entry, body, actor)
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, result)
        return True

    # /drafts/{id}/preview
    match = re.match(r'^/drafts/([0-9a-f]{32})/preview$', path)
    if match:
        draft_id = match.group(1)
        allowed = {'revision', 'mode', 'replace_id'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        try:
            result = review.prepare_publish(draft_id, body, actor, session['csrf'])
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, result)
        return True

    # /drafts/{id}/publish
    match = re.match(r'^/drafts/([0-9a-f]{32})/publish$', path)
    if match:
        draft_id = match.group(1)
        allowed = {'revision', 'token', 'confirm', 'password'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        if not _password_ok(handler, session, body, client):
            return True
        try:
            result = review.publish(draft_id, body, actor, session['csrf'])
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, result)
        return True

    # /rollback-preview
    if path == '/rollback-preview':
        allowed = {'release_id'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        try:
            result = review.prepare_rollback(body, actor, session['csrf'])
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, result)
        return True

    # /rollback
    if path == '/rollback':
        allowed = {'release_id', 'token', 'confirm', 'password'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        if not _password_ok(handler, session, body, client):
            return True
        try:
            result = review.rollback(body, actor, session['csrf'])
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, result)
        return True

    # /unpublish
    if path == '/unpublish':
        allowed = {'faq_id', 'expected_release_id', 'confirm', 'password'}
        if not set(body.keys()).issubset(allowed):
            handler.respond(400, {'error': 'Unexpected keys in body'})
            return True
        if not _password_ok(handler, session, body, client):
            return True
        try:
            result = review.unpublish(body, actor, session['csrf'])
        except Exception as exc:
            return _handle_exception(handler, exc)
        handler.respond(200, result)
        return True

    # Unknown POST path
    handler.respond(404, {'error': 'Not found'})
    return True
