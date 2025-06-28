"""
Tests for diagnostics decorators and utilities.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import unittest
import json
from unittest.mock import MagicMock, patch
from flask import Flask
from diagnostics import ResponseFormatter, track_metrics

class TestResponseFormatter(unittest.TestCase):
    def test_add_diagnostics(self):
        """Test adding diagnostics to different response formats."""
        # Test with simple output text
        data = {'output': 'Hello', 'model': 'gpt-4'}
        formatted = ResponseFormatter.add_diagnostics(data, '|DIAG|')
        self.assertEqual(formatted['output'], 'Hello|DIAG|')
        
        # Test with choices array
        data = {'choices': [{'text': 'Hi'}]}
        formatted = ResponseFormatter.add_diagnostics(data, '|DIAG|')
        self.assertEqual(formatted['choices'][0]['text'], 'Hi|DIAG|')
        
        # Test with message content
        data = {'choices': [{'message': {'content': 'Hey'}}]}
        formatted = ResponseFormatter.add_diagnostics(data, '|DIAG|')
        self.assertEqual(formatted['choices'][0]['message']['content'], 'Hey|DIAG|')

class TestTrackMetricsDecorator(unittest.TestCase):
    @patch('diagnostics.session_manager')
    def test_track_metrics(self, mock_session):
        """Test the metrics tracking decorator with proper Flask context."""
        # Setup mock session and response
        mock_tracker = MagicMock()
        mock_tracker.get_diagnostic_info.return_value = '|METRICS|'
        mock_session.get_session.return_value = {'cost_tracker': mock_tracker}
        
        # Create a mock Flask response
        class MockResponse:
            def __init__(self):
                self.data = None
                
            def get_json(self):
                return json.loads(self.data) if self.data else None
                
            def set_data(self, data):
                self.data = data
                
        mock_response = MockResponse()
        mock_response.set_data(json.dumps({'status': 'success', 'model': 'gpt-4', 'output': 'test'}))
        
        # Create test function
        @track_metrics()
        def test_func():
            return mock_response
        
        # Create Flask app context
        app = Flask(__name__)
        with app.test_request_context():
            # Set session_id in g
            from flask import g
            g.session_id = 'test_session'
            
            # Call and verify
            result = test_func()
            response_data = json.loads(result.data)
            self.assertEqual(response_data['output'], 'test|METRICS|')
            mock_session.get_session.assert_called_once_with('test_session')

if __name__ == '__main__':
    unittest.main()
