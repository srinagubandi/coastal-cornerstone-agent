import pytest
from unittest.mock import MagicMock, patch
import json
import os
import sys

# Ensure the project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import admin_faq_http
from config import ADMIN_EMAIL, RECIPIENT


class MockHandler:
    def __init__(self, service, path='', method='GET'):
        self.service = service
        self.path = path
        self.command = method
        self.headers = {}
        self.response_status = None
        self.response_body = None
        self.response_extra = None

    def respond(self, status, value=None, content_type="application/json; charset=utf-8", extra=None):
        self.response_status = status
        self.response_body = value
        self.response_extra = extra

    def context(self):
        return 'mock-client-hash'


@pytest.fixture
def mock_service():
    s = MagicMock()
    s.store = MagicMock()
    s.faq_review = MagicMock()
    s.agent = MagicMock()
    s.chat = MagicMock()
    s.config = MagicMock()
    s.config.admin_hash = 'admin_hash'
    s.config.ben_admin_hash = 'ben_hash'
    s.dashboard = MagicMock()
    s.dashboard.hash_slots = MagicMock()
    s.dashboard.hash_slots.acquire = MagicMock(return_value=True)
    s.dashboard.hash_slots.release = MagicMock()
    s.store.rate = MagicMock(return_value=(True, 0))
    return s


@pytest.fixture
def handler(mock_service):
    return MockHandler(mock_service)


@pytest.fixture
def admin_session():
    return {'role': 'admin', 'csrf': 'token123'}


@pytest.fixture
def ben_session():
    return {'role': 'ben', 'csrf': 'token456'}


# --------------------- handle_get tests ---------------------

def test_handle_get_no_session(handler):
    admin_faq_http.handle_get(handler, '/drafts', None)
    assert handler.response_status == 401


def test_handle_get_invalid_role(handler):
    session = {'role': 'unknown', 'csrf': 'token'}
    admin_faq_http.handle_get(handler, '/drafts', session)
    assert handler.response_status == 401


def test_handle_get_query_reject(handler, admin_session):
    handler.path = '/drafts?foo=bar'
    admin_faq_http.handle_get(handler, '/drafts', admin_session)
    assert handler.response_status == 400
    assert 'Query parameters' in handler.response_body['error']


def test_handle_get_drafts(handler, admin_session, mock_service):
    mock_service.faq_review.list_drafts.return_value = [{'id': 'draft1'}]
    mock_service.agent.public_faq.return_value = {'faqs': []}
    mock_service.faq_review.release_list.return_value = []
    admin_faq_http.handle_get(handler, '/drafts', admin_session)
    assert handler.response_status == 200
    assert 'items' in handler.response_body
    assert 'published' in handler.response_body


def test_handle_get_draft_detail_found(handler, admin_session, mock_service):
    draft_id = 'a' * 32
    mock_service.faq_review.detail.return_value = {'id': draft_id, 'question': 'test'}
    admin_faq_http.handle_get(handler, f'/drafts/{draft_id}', admin_session)
    assert handler.response_status == 200
    assert handler.response_body['id'] == draft_id


def test_handle_get_draft_detail_not_found(handler, admin_session, mock_service):
    mock_service.faq_review.detail.return_value = None
    admin_faq_http.handle_get(handler, '/drafts/' + 'a'*32, admin_session)
    assert handler.response_status == 404


def test_handle_get_audit(handler, admin_session, mock_service):
    mock_service.faq_review.audit_list.return_value = [{'action': 'create'}]
    admin_faq_http.handle_get(handler, '/audit', admin_session)
    assert handler.response_status == 200
    assert handler.response_body == {'items': [{'action': 'create'}]}


def test_handle_get_review_queue_list(handler, admin_session, mock_service):
    mock_service.faq_review.review_queue.return_value = [{'id': 1}, {'id': 2}]
    admin_faq_http.handle_get(handler, '/review-queue', admin_session)
    assert handler.response_status == 200
    assert handler.response_body == {'count': 2, 'items': [{'id': 1}, {'id': 2}]}


def test_handle_get_review_queue_dict(handler, admin_session, mock_service):
    mock_service.faq_review.review_queue.return_value = {'count': 5, 'items': []}
    admin_faq_http.handle_get(handler, '/review-queue', admin_session)
    assert handler.response_status == 200
    assert handler.response_body == {'count': 5, 'items': []}


def test_handle_get_unknown_path(handler, admin_session):
    admin_faq_http.handle_get(handler, '/unknown', admin_session)
    assert handler.response_status == 404


# --------------------- handle_post tests ---------------------

def test_handle_post_no_session(handler):
    admin_faq_http.handle_post(handler, '/drafts/abc/save', {}, None, 'client')
    assert handler.response_status == 401


def test_handle_post_invalid_role(handler):
    session = {'role': 'unknown', 'csrf': 'token'}
    admin_faq_http.handle_post(handler, '/drafts/abc/save', {}, session, 'client')
    assert handler.response_status == 401


def test_handle_post_query_reject(handler, admin_session):
    handler.path = '/drafts/abc/save?foo=bar'
    admin_faq_http.handle_post(handler, '/drafts/abc/save', {}, admin_session, 'client')
    assert handler.response_status == 400


def test_handle_post_body_not_dict(handler, admin_session):
    admin_faq_http.handle_post(handler, '/drafts/abc/save', 'not a dict', admin_session, 'client')
    assert handler.response_status == 400


def test_handle_post_save_success(handler, admin_session, mock_service):
    draft_id = 'a' * 32
    body = {'question': 'What?'}
    mock_service.faq_review.save.return_value = None
    mock_service.faq_review.detail.return_value = {'id': draft_id, 'question': 'What?', 'revision': 2}
    admin_faq_http.handle_post(handler, f'/drafts/{draft_id}/save', body, admin_session, 'client')
    assert handler.response_status == 200
    mock_service.faq_review.save.assert_called_once_with(draft_id, body, ADMIN_EMAIL)
    mock_service.faq_review.detail.assert_called_once_with(draft_id)
    assert handler.response_body['revision'] == 2


def test_handle_post_save_conflict(handler, admin_session, mock_service):
    from faq_review import Conflict
    mock_service.faq_review.save.side_effect = Conflict('revision conflict')
    admin_faq_http.handle_post(handler, '/drafts/' + 'a'*32 + '/save', {'question': 'Q'}, admin_session, 'client')
    assert handler.response_status == 409
    assert 'revision conflict' in handler.response_body['error']


def test_handle_post_save_published_state(handler, admin_session):
    admin_faq_http.handle_post(handler, '/drafts/' + 'a'*32 + '/save', {'state': 'published'}, admin_session, 'client')
    assert handler.response_status == 400


def test_handle_post_entry_review(handler, admin_session, mock_service):
    mock_service.chat.update_entry.return_value = None
    mock_service.chat.get_entry.return_value = {'id': 1, 'classification': 'approved', 'revision': 3}
    body = {'classification': 'approved', 'revision': 2}
    admin_faq_http.handle_post(handler, '/entries/1/review', body, admin_session, 'client')
    assert handler.response_status == 200
    mock_service.chat.update_entry.assert_called_once_with(1, 'approved', 2, ADMIN_EMAIL)
    assert handler.response_body == {'id': 1, 'classification': 'approved', 'revision': 3}


def test_handle_post_promote(handler, admin_session, mock_service):
    mock_service.chat.get_entry.return_value = {'id': 1, 'question': 'Q'}
    mock_service.faq_review.promote.return_value = {'draft_id': 'new'}
    body = {'revision': 1, 'question': 'Q', 'source_urls': []}
    admin_faq_http.handle_post(handler, '/entries/1/promote', body, admin_session, 'client')
    assert handler.response_status == 200
    mock_service.faq_review.promote.assert_called_once()


def test_handle_post_publish_wrong_password(handler, admin_session, mock_service):
    with patch('admin_faq_http.verify_password', return_value=False):
        body = {'password': 'wrong', 'revision': 1, 'token': 'x', 'confirm': True}
        admin_faq_http.handle_post(handler, '/drafts/' + 'a'*32 + '/publish', body, admin_session, 'client')
    assert handler.response_status == 403
    assert 'password' not in body  # stripped


def test_handle_post_publish_rate_limited(handler, admin_session, mock_service):
    mock_service.store.rate.return_value = (False, 30)
    body = {'password': 'pass', 'revision': 1, 'token': 'x', 'confirm': True}
    admin_faq_http.handle_post(handler, '/drafts/' + 'a'*32 + '/publish', body, admin_session, 'client')
    assert handler.response_status == 429


def test_handle_post_publish_hash_slot_busy(handler, admin_session, mock_service):
    mock_service.dashboard.hash_slots.acquire.return_value = False
    body = {'password': 'pass', 'revision': 1, 'token': 'x', 'confirm': True}
    admin_faq_http.handle_post(handler, '/drafts/' + 'a'*32 + '/publish', body, admin_session, 'client')
    assert handler.response_status == 503


def test_handle_post_publish_success(handler, admin_session, mock_service):
    with patch('admin_faq_http.verify_password', return_value=True):
        mock_service.faq_review.publish.return_value = {'status': 'published'}
        body = {'password': 'correct', 'revision': 1, 'token': 'x', 'confirm': True}
        admin_faq_http.handle_post(handler, '/drafts/' + 'a'*32 + '/publish', body, admin_session, 'client')
    assert handler.response_status == 200
    mock_service.faq_review.publish.assert_called_once()
    assert 'password' not in body


def test_handle_post_unknown_path(handler, admin_session):
    admin_faq_http.handle_post(handler, '/unknown', {}, admin_session, 'client')
    assert handler.response_status == 404


# --------------------- actor tests ---------------------

def test_actor_admin():
    session = {'role': 'admin'}
    assert admin_faq_http._actor(session) == ADMIN_EMAIL


def test_actor_ben():
    session = {'role': 'ben'}
    assert admin_faq_http._actor(session) == RECIPIENT


def test_actor_default():
    session = {}
    assert admin_faq_http._actor(session) == RECIPIENT


# --------------------- Service sanity / seed import ---------------------

def test_service_init_sanity(tmp_path):
    """Service can be instantiated with empty credentials and a temp dir."""
    os.environ['OPENROUTER_API_KEY'] = ''
    os.environ['RESEND_API_KEY'] = ''
    os.environ['ADMIN_PASSWORD_HASH'] = ''
    os.environ['BEN_ADMIN_PASSWORD_HASH'] = ''
    os.environ['CHAT_ENABLED'] = 'false'
    os.environ['DIGEST_ENABLED'] = 'false'
    os.environ['PUBLIC_ORIGIN'] = 'http://localhost:3000'
    os.environ['FAQ_REVIEW_SEED_JSON'] = ''
    from config import Config
    from app import Service
    config = Config(data_dir=tmp_path)
    service = Service(config=config)
    assert hasattr(service, 'faq_review')


def test_service_seed_import(tmp_path):
    """Seed JSON is imported when FAQ_REVIEW_SEED_JSON is set."""
    seed_data = [{'question': 'seed Q', 'answer': 'A'}]
    os.environ['FAQ_REVIEW_SEED_JSON'] = json.dumps(seed_data)
    os.environ['OPENROUTER_API_KEY'] = ''
    os.environ['RESEND_API_KEY'] = ''
    os.environ['ADMIN_PASSWORD_HASH'] = ''
    os.environ['BEN_ADMIN_PASSWORD_HASH'] = ''
    os.environ['CHAT_ENABLED'] = 'false'
    os.environ['DIGEST_ENABLED'] = 'false'
    os.environ['PUBLIC_ORIGIN'] = 'http://localhost:3000'
    from config import Config
    from app import Service
    with patch('app.FAQReview') as MockFAQReview:
        mock_review_instance = MockFAQReview.return_value
        config = Config(data_dir=tmp_path)
        service = Service(config=config)
        mock_review_instance.import_questions.assert_called_once_with(seed_data, actor='system:seed')
