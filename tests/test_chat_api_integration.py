"""
Integration tests for the chat API.

These tests verify the integration between chat_api, session_store,
and chat_handler modules.
"""
import unittest
import json
from unittest.mock import patch, MagicMock

from MyGrok3.app import create_app
from MyGrok3.session_store import get_session_store

class ChatApiIntegrationTest(unittest.TestCase):
    """Integration tests for chat API endpoints."""
    
    def setUp(self):
        """Set up test environment with a test Flask client."""
        # Create the application with test config
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test_key'
        
        # Create a test client
        self.client = self.app.test_client()
        
        # Get the session store singleton
        self.session_store = get_session_store()
        
        # Clear any existing sessions
        self.session_store._sessions = {}
        self.session_store._global_stats = {
            "total_tokens": 0,
            "total_cost": 0.0,
            "requests_count": 0,
            "models_usage": {}
        }
    
    @patch('MyGrok3.chat_handler.stream_chat_completion')
    @patch('MyGrok3.chat_handler.get_chat_completion')
    def test_chat_endpoint_non_streaming(self, mock_get_completion, mock_stream_completion):
        """Test the /api/chat endpoint with non-streaming mode."""
        # Mock the chat completion response
        mock_get_completion.return_value = {
            "model": "test-model",
            "content": "This is a test response",
            "tokens_in": 10,
            "tokens_out": 20,
            "cost": 0.001
        }
        
        # Test data
        data = {
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "test-model",
            "stream": False
        }
        
        # Make the request
        response = self.client.post(
            '/api/chat',
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Check response
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        
        # Verify response structure
        self.assertIn("model", response_data)
        self.assertIn("content", response_data)
        self.assertIn("tokens_in", response_data)
        self.assertIn("tokens_out", response_data)
        self.assertIn("cost", response_data)
        
        # Verify session was updated
        sessions = self.session_store._sessions
        self.assertEqual(len(sessions), 1)
        
        # Get the session ID (there should be only one)
        session_id = list(sessions.keys())[0]
        session = sessions[session_id]
        
        # Verify session data
        self.assertEqual(session["token_count"], 30)  # 10 in + 20 out
        self.assertEqual(session["total_cost"], 0.001)
        self.assertEqual(session["requests_count"], 1)
        self.assertEqual(len(session["messages"]), 2)  # User message + AI response
        
        # Verify global stats
        global_stats = self.session_store.get_global_stats()
        self.assertEqual(global_stats["total_tokens"], 30)
        self.assertEqual(global_stats["total_cost"], 0.001)
        self.assertEqual(global_stats["requests_count"], 1)
        
    @patch('MyGrok3.chat_handler.stream_chat_completion')
    def test_chat_endpoint_streaming(self, mock_stream_completion):
        """Test the /api/chat endpoint with streaming mode."""
        # Mock the streaming response
        class MockResponse:
            def __init__(self):
                self.status_code = 200
                self.headers = {}
                
            def iter_lines(self):
                yield b'data: {"id": "test-id", "model": "test-model", "choices": [{"delta": {"content": "This"}}]}'
                yield b'data: {"id": "test-id", "model": "test-model", "choices": [{"delta": {"content": " is"}}]}'
                yield b'data: {"id": "test-id", "model": "test-model", "choices": [{"delta": {"content": " streaming"}}]}'
                yield b'data: {"id": "test-id", "model": "test-model", "choices": [{"finish_reason": "stop"}]}'
                yield b'data: [DONE]'
        
        mock_stream_completion.return_value = (MockResponse(), "test-model", 10, 20, 0.002)
        
        # Test data
        data = {
            "messages": [{"role": "user", "content": "Hello stream"}],
            "model": "test-model",
            "stream": True
        }
        
        # Make the request
        response = self.client.post(
            '/api/chat',
            data=json.dumps(data),
            content_type='application/json',
            stream=True
        )
        
        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Read streaming response data
        response_text = b''
        for chunk in response.response:
            response_text += chunk
            
        # Basic verification of streaming response
        self.assertIn(b'data: {"id": "test-id"', response_text)
        
        # Verify session was updated
        sessions = self.session_store._sessions
        self.assertEqual(len(sessions), 1)
        
        # Get the session ID (there should be only one)
        session_id = list(sessions.keys())[0]
        session = sessions[session_id]
        
        # Verify session data was updated with streaming stats
        self.assertEqual(session["token_count"], 30)  # 10 in + 20 out
        self.assertEqual(session["total_cost"], 0.002)
        self.assertEqual(session["requests_count"], 1)
        self.assertEqual(len(session["messages"]), 2)  # User message + AI response
        
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
            
        response = self.client.get('/api/session_stats')
        
        # Check response
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        
        # Verify response data
        self.assertEqual(response_data["token_count"], 200)
        self.assertEqual(response_data["total_cost"], 0.005)
        self.assertEqual(response_data["requests_count"], 1)
        
    @patch('MyGrok3.chat_handler.get_chat_completion')
    def test_title_summary_endpoint(self, mock_get_completion):
        """Test the /api/title_summary endpoint."""
        # Mock the chat completion response
        mock_get_completion.return_value = {
            "model": "test-model",
            "content": json.dumps({
                "title": "Test Conversation",
                "summary": "This is a test summary"
            }),
            "tokens_in": 30,
            "tokens_out": 10,
            "cost": 0.0008
        }
        
        # Add some messages to a session
        session_id = "test-title-summary"
        self.session_store.get_session(session_id)
        self.session_store.add_message(session_id, {"role": "user", "content": "Hello"})
        self.session_store.add_message(session_id, {"role": "assistant", "content": "Hi there"})
        
        # Make the request with session cookie
        with self.client.session_transaction() as session:
            session['session_id'] = session_id
            
        response = self.client.post('/api/title_summary')
        
        # Check response
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        
        # Verify response structure
        self.assertIn("title", response_data)
        self.assertIn("summary", response_data)
        self.assertEqual(response_data["title"], "Test Conversation")
        self.assertEqual(response_data["summary"], "This is a test summary")
        
        # Verify session stats were updated
        session = self.session_store.get_session(session_id)
        self.assertEqual(session["token_count"], 40)  # 30 in + 10 out
        self.assertEqual(session["total_cost"], 0.0008)
        
if __name__ == '__main__':
    unittest.main()
