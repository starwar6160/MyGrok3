"""
Unit tests for the chat_handler module.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from chat_handler import generate_title, ask_llm, ask_llm_stream

class TestChatHandler(unittest.TestCase):
    """Test cases for chat handling logic."""

    @patch('chat_handler.ask_llm')
    def test_generate_title_success(self, mock_ask_llm):
        """Test successful title generation."""
        # Mock the response from the LLM
        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=' "测试标题" '))
            ]
        )
        mock_ask_llm.return_value = mock_response

        history = [{"role": "user", "content": "你好"}]
        title = generate_title(history)

        # Verify the title is cleaned and correct
        self.assertEqual(title, "测试标题")
        mock_ask_llm.assert_called_once()

    def test_generate_title_empty_history(self):
        """Test title generation with empty history."""
        title = generate_title([])
        self.assertEqual(title, "新会话")

    @patch('chat_handler.add_to_cache')
    @patch('chat_handler.get_from_cache', return_value=None)
    @patch('chat_handler.client.chat.completions.create')
    def test_ask_llm_cache_miss_and_success(self, mock_create, mock_get_from_cache, mock_add_to_cache):
        """Test ask_llm on a cache miss and successful API call."""
        mock_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="API response"))])
        mock_create.return_value = mock_response
        
        model = "test-model"
        messages = [{"role": "user", "content": "Hello"}]
        
        response = ask_llm(model, messages)
        
        mock_get_from_cache.assert_called_once_with(model, messages)
        mock_create.assert_called_once_with(model=model, messages=messages, stream=False)
        mock_add_to_cache.assert_called_once_with(model, messages, mock_response)
        self.assertEqual(response, mock_response)

    @patch('chat_handler.client.chat.completions.create')
    @patch('chat_handler.get_from_cache')
    def test_ask_llm_cache_hit(self, mock_get_from_cache, mock_create):
        """Test ask_llm on a cache hit."""
        cached_response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Cached response"))])
        mock_get_from_cache.return_value = cached_response
        
        model = "test-model"
        messages = [{"role": "user", "content": "Hello"}]
        
        response = ask_llm(model, messages)
        
        mock_get_from_cache.assert_called_once_with(model, messages)
        mock_create.assert_not_called()
        self.assertEqual(response, cached_response)

    @patch('chat_handler.get_from_cache', return_value=None)
    @patch('chat_handler.client.chat.completions.create')
    def test_ask_llm_api_error(self, mock_create, mock_get_from_cache):
        """Test ask_llm when the API call fails."""
        mock_create.side_effect = Exception("API Error")
        
        model = "test-model"
        messages = [{"role": "user", "content": "Hello"}]
        
        response = ask_llm(model, messages)
        
        self.assertIn("error", response)
        self.assertIn("API Error", response["error"])

    @patch('chat_handler.client.chat.completions.create')
    def test_ask_llm_stream_success(self, mock_create):
        """Test successful streaming with ask_llm_stream."""
        # Create a mock generator for the streaming response
        def mock_stream_generator():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello "))], usage=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="World"))], usage=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20))

        mock_create.return_value = mock_stream_generator()
        
        model = "test-model"
        messages = [{"role": "user", "content": "Stream this"}]
        
        result = list(ask_llm_stream(model, messages))
        
        mock_create.assert_called_once_with(model=model, messages=messages, stream=True)
        
        # Check the yielded content
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "Hello ")
        self.assertEqual(result[1], "World")
        
        # Check the final usage object
        self.assertEqual(result[2].prompt_tokens, 10)
        self.assertEqual(result[2].completion_tokens, 20)

    @patch('chat_handler.client.chat.completions.create')
    def test_ask_llm_stream_api_error(self, mock_create):
        """Test ask_llm_stream when the API call fails."""
        mock_create.side_effect = Exception("Stream Error")
        
        model = "test-model"
        messages = [{"role": "user", "content": "Stream this"}]
        
        result = list(ask_llm_stream(model, messages))
        
        self.assertEqual(len(result), 1)
        self.assertIn("Error in streaming response", result[0])
        self.assertIn("Stream Error", result[0])


if __name__ == '__main__':
    unittest.main()