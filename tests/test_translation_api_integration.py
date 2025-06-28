"""
Integration tests for the translation API.

These tests verify the functionality of the translation endpoints,
ensuring they behave as expected before and after refactoring.
"""
import unittest
import json
from unittest.mock import patch
from types import SimpleNamespace

from app import create_app
from chat_handler import FinalStats

class TranslationApiIntegrationTest(unittest.TestCase):
    """Integration tests for translation API endpoints."""

    def setUp(self):
        """Set up a test Flask client for each test."""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    @patch('translation_api.ask_llm')
    def test_translate_endpoint_non_stream(self, mock_ask_llm):
        """Test the /api/translate endpoint in non-streaming mode."""
        # Mock the response from the underlying LLM call
        mock_ask_llm.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        )

        data = {"text": "你好", "target_lang": "en", "stream": False}
        response = self.client.post('/translation/api/translate', data=json.dumps(data), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        self.assertIn("Hello", response_data['translated_text'])
        self.assertIn("diagnostics", response_data)
        mock_ask_llm.assert_called_once()

    @patch('translation_api.generate_chat_response')
    def test_translate_endpoint_stream(self, mock_generate_chat_response):
        """Test the /api/translate endpoint in streaming mode."""
        # Mock the generator that yields content and final stats
        def mock_generator(*args, **kwargs):
            yield "Hello"
            yield FinalStats("test-model", 10, 5, 0.001, "Hello")

        mock_generate_chat_response.return_value = mock_generator()

        data = {"text": "你好", "target_lang": "en", "stream": True}
        response = self.client.post('/translation/api/translate', data=json.dumps(data), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_streamed)
        
        streamed_data = b"".join(response.response).decode('utf-8')
        self.assertIn('data: {"content": "Hello"}', streamed_data)
        self.assertIn('data: [DONE]', streamed_data)
        self.assertIn('diagnostics', streamed_data) # Check for the final footer
        mock_generate_chat_response.assert_called_once()

    @patch('translation_api.ask_llm')
    def test_process_with_english_model_non_stream(self, mock_ask_llm):
        """Test the /api/process-with-english-model endpoint in non-streaming mode."""
        # Mock the 3-step process by providing a sequence of return values
        mock_ask_llm.side_effect = [
            # 1. Translate to English
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Hello"))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)
            ),
            # 2. English model response
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Hi there, how can I help?"))],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10)
            ),
            # 3. Back-translate to Chinese
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="你好，我能怎么帮你？"))],
                usage=SimpleNamespace(prompt_tokens=15, completion_tokens=10)
            )
        ]

        data = {"text": "你好", "stream": False, "history": []}
        response = self.client.post('/translation/api/process-with-english-model', data=json.dumps(data), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        self.assertIn("response", response_data)
        # Check for content from all 3 steps and the final diagnostics
        self.assertIn("Hello", response_data['response'])
        self.assertIn("Hi there, how can I help?", response_data['response'])
        self.assertIn("你好，我能怎么帮你？", response_data['response'])
        self.assertIn("diagnostics", response_data['response'])
        self.assertEqual(mock_ask_llm.call_count, 3)

    @patch('translation_api._unified_processing_generator')
    def test_process_with_english_model_stream(self, mock_processing_generator):
        """Test the /api/process-with-english-model endpoint in streaming mode."""
        # Mock the new unified generator that yields strings and FinalStats
        def mock_generator(*args, **kwargs):
            # Step 1
            yield "--- [步骤 1: 将问题翻译为英文] ---\n"
            yield FinalStats("translation-model", 10, 5, 0.001, "Hello")
            yield "Hello\n\n"
            # Step 2
            yield "--- [步骤 2: 使用英文模型处理] ---\n"
            yield "Hi there, "
            yield "how can I help?\n\n"
            yield FinalStats("english-model", 20, 10, 0.002, "Hi there, how can I help?")
            # Step 3
            yield "--- [步骤 3: 将回复翻译回中文] ---\n"
            yield "你好，我能怎么帮你？"
            yield FinalStats("translation-model", 15, 10, 0.0015, "你好，我能怎么帮你？")

        mock_processing_generator.return_value = mock_generator()

        data = {"text": "你好", "stream": True, "history": []}
        response = self.client.post('/translation/api/process-with-english-model', data=json.dumps(data), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_streamed)
        
        streamed_data = b"".join(response.response).decode('utf-8')
        self.assertIn("Hello", streamed_data)
        self.assertIn("Hi there, how can I help?", streamed_data)
        self.assertIn("你好，我能怎么帮你？", streamed_data)
        self.assertIn("diagnostics", streamed_data) # The wrapper adds this at the end
        mock_processing_generator.assert_called_once()

if __name__ == '__main__':
    unittest.main()