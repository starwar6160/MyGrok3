"""
Integration tests for the chat API.

These tests verify the integration between chat_api, session_store,
and chat_handler modules.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import unittest
import json
from unittest.mock import patch

from app import create_app
from session_store import get_session_store, _reset_session_store_for_testing
from chat_handler import FinalStats

class ChatApiIntegrationTest(unittest.TestCase):
    """Integration tests for chat API endpoints."""
    
    def setUp(self):
        """Set up test environment with a test Flask client."""
        # Reset the session store singleton and delete the DB file for a clean state
        _reset_session_store_for_testing()
        if os.path.exists(get_session_store().DB_FILE):
            os.remove(get_session_store().DB_FILE)

        # Create the application with test config
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'

        # Create a test client
        self.client = self.app.test_client()

        # Get the session store singleton
        self.session_store = get_session_store()
    
    @patch('chat_api.generate_chat_response')
    def test_chat_endpoint_streaming(self, mock_generate_chat_response):
        """Test the /api/chat endpoint with streaming mode."""

        # Use a valid model ID from models_config.py
        valid_model_id = "x-ai/grok-3-mini"

        # Mock the generator returned by generate_chat_response
        def mock_generator(*args, **kwargs):
            yield "This is "
            yield "a streaming test."
            yield FinalStats(
                model_name=valid_model_id,
                input_tokens=10,
                output_tokens=20,
                estimated_cost=0.002,
                full_answer="This is a streaming test."
            )

        mock_generate_chat_response.return_value = mock_generator()

        data = {
            "question": "Hello",
            "history": [],
            "model": valid_model_id
        }

        # Make the request
        response = self.client.post(
            '/api/chat',
            data=json.dumps(data),
            content_type='application/json'
        )

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_streamed)

        # Read streaming response data
        response_text = b''.join(response.response)
        self.assertIn(b"This is a streaming test.", response_text)

        # Verify session was updated
        sessions = self.session_store._sessions
        self.assertEqual(len(sessions), 1)

        session_id = list(sessions.keys())[0]
        session = sessions[session_id]

        # Verify session data was updated with streaming stats
        self.assertEqual(session["token_count"], 30)
        self.assertAlmostEqual(session["total_cost"], 0.002)
        self.assertEqual(session["requests_count"], 1)
        self.assertEqual(len(session["messages"]), 2)  # User message + AI response
        self.assertEqual(session["messages"][1]["content"], "This is a streaming test.")

    def test_session_stats_endpoint(self):
        """Test the /api/session_stats endpoint."""
        # Add some test data to session store
        session_id = "test-session-stats"
        self.session_store.get_session(session_id)
        self.session_store.update_stats(
            session_id,
            model="test-model",
            tokens_in=50,
            tokens_out=150,
            cost=0.005
        )

        # Make the request with session cookie
        with self.client.session_transaction() as session:
            session['session_id'] = session_id

        response = self.client.get('/api/session_stats', headers={'Content-Type': 'application/json'})

        # Check response
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)

        # Verify response data
        self.assertEqual(response_data["session_stats"]["token_count"], 200)
        self.assertEqual(response_data["session_stats"]["total_cost"], 0.005)
        self.assertEqual(response_data["session_stats"]["requests_count"], 1)

    def test_title_summary_endpoint(self):
        """Test the /api/title_summary endpoint."""
        # Add some messages to a session
        session_id = "test-title-summary"
        self.session_store.get_session(session_id)
        self.session_store.add_message(session_id, {"role": "user", "content": "Hello"})

        # Make the request with session cookie
        with self.client.session_transaction() as session:
            session['session_id'] = session_id

        history = self.session_store.get_session(session_id)['messages']
        response = self.client.post('/api/title_summary', data=json.dumps({"messages": history}), content_type='application/json')

        # Check response
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)

        # Verify response structure (placeholders)
        self.assertIn("title", response_data)
        self.assertIn("summary", response_data)
        self.assertEqual(response_data['title'], '重复问候')
        self.assertEqual(response_data["summary"], "Generated Summary")

        # Verify session stats were NOT updated, as the current implementation uses placeholders
        session = self.session_store.get_session(session_id)
        self.assertEqual(session["token_count"], 0)
        self.assertEqual(session["total_cost"], 0)
        
if __name__ == '__main__':
    unittest.main()
