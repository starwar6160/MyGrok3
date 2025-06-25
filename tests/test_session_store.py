"""
Unit tests for the session_store module.

This module tests the thread-safe session store implementation.
"""
import unittest
import time
from datetime import datetime
import threading

from MyGrok3.session_store import SessionStore, get_session_store

class TestSessionStore(unittest.TestCase):
    """Test cases for the SessionStore class."""
    
    def setUp(self):
        """Set up a fresh SessionStore instance for each test."""
        # Create a dedicated instance for testing, not using the global singleton
        self.store = SessionStore()
        
    def test_get_session(self):
        """Test getting and creating sessions."""
        # Get a new session
        session = self.store.get_session("test-session-1")
        
        # Check that it has the expected structure
        self.assertIsInstance(session, dict)
        self.assertIn("created_at", session)
        self.assertIn("last_active", session)
        self.assertIn("messages", session)
        self.assertEqual(session["messages"], [])
        self.assertEqual(session["token_count"], 0)
        self.assertEqual(session["total_cost"], 0.0)
        
        # Get the same session again and check it's the same data
        session2 = self.store.get_session("test-session-1")
        self.assertEqual(session["created_at"], session2["created_at"])
        
    def test_update_session(self):
        """Test updating session data."""
        # Create a session
        self.store.get_session("test-session-2")
        
        # Update it
        self.store.update_session(
            "test-session-2",
            token_count=100,
            total_cost=1.23,
            metadata={"key": "value"}
        )
        
        # Check the updates
        session = self.store.get_session("test-session-2")
        self.assertEqual(session["token_count"], 100)
        self.assertEqual(session["total_cost"], 1.23)
        self.assertEqual(session["metadata"], {"key": "value"})
        
    def test_add_get_messages(self):
        """Test adding and retrieving messages."""
        # Add some messages
        self.store.add_message("test-session-3", {"role": "user", "content": "Hello"})
        self.store.add_message("test-session-3", {"role": "assistant", "content": "Hi there"})
        
        # Check messages were added
        messages = self.store.get_messages("test-session-3")
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Hello")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "Hi there")
        
    def test_update_stats(self):
        """Test updating session and global statistics."""
        # Update stats for a session
        self.store.update_stats(
            "test-session-4",
            model="test-model",
            tokens_in=10,
            tokens_out=20,
            cost=0.005
        )
        
        # Check session stats
        session = self.store.get_session("test-session-4")
        self.assertEqual(session["token_count"], 30)  # 10 in + 20 out
        self.assertEqual(session["total_cost"], 0.005)
        self.assertEqual(session["requests_count"], 1)
        self.assertEqual(session["models_used"], {"test-model": 1})
        
        # Check global stats
        global_stats = self.store.get_global_stats()
        self.assertEqual(global_stats["total_tokens"], 30)
        self.assertEqual(global_stats["total_cost"], 0.005)
        self.assertEqual(global_stats["requests_count"], 1)
        self.assertEqual(global_stats["models_usage"]["test-model"], 1)
        
        # Update stats again
        self.store.update_stats(
            "test-session-4",
            model="test-model",
            tokens_in=5,
            tokens_out=15,
            cost=0.003
        )
        
        # Check updated stats
        session = self.store.get_session("test-session-4")
        self.assertEqual(session["token_count"], 50)  # 30 + 5 + 15
        self.assertEqual(session["total_cost"], 0.008)  # 0.005 + 0.003
        self.assertEqual(session["requests_count"], 2)
        self.assertEqual(session["models_used"], {"test-model": 2})
        
    def test_delete_session(self):
        """Test deleting a session."""
        # Create a session
        self.store.get_session("test-session-5")
        
        # Delete it
        result = self.store.delete_session("test-session-5")
        self.assertTrue(result)
        
        # Try to delete non-existent session
        result = self.store.delete_session("non-existent")
        self.assertFalse(result)
        
    def test_export_session(self):
        """Test exporting session data."""
        # Create and populate a session
        self.store.get_session("test-session-6")
        self.store.add_message("test-session-6", {"role": "user", "content": "Test"})
        self.store.update_stats("test-session-6", model="test-model", tokens_in=5, tokens_out=10, cost=0.001)
        
        # Export it
        session_data = self.store.export_session("test-session-6")
        self.assertIsNotNone(session_data)
        self.assertEqual(len(session_data["messages"]), 1)
        self.assertEqual(session_data["token_count"], 15)
        
        # Try to export non-existent session
        session_data = self.store.export_session("non-existent")
        self.assertIsNone(session_data)
        
    def test_singleton(self):
        """Test the singleton pattern of get_session_store."""
        # Get two instances
        store1 = get_session_store()
        store2 = get_session_store()
        
        # They should be the same object
        self.assertIs(store1, store2)
        
    def test_thread_safety(self):
        """Test thread safety of the session store."""
        # Create a shared session
        self.store.get_session("thread-test")
        
        # Function to update the session from a thread
        def update_session(thread_id):
            for i in range(100):
                self.store.update_stats(
                    "thread-test",
                    model=f"model-{thread_id}",
                    tokens_in=1,
                    tokens_out=1,
                    cost=0.0001
                )
        
        # Create and start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=update_session, args=(i,))
            threads.append(thread)
            thread.start()
            
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
            
        # Check the session data
        session = self.store.get_session("thread-test")
        
        # Should have 10 threads * 100 updates each = 1000 total updates
        self.assertEqual(session["requests_count"], 1000)
        self.assertEqual(session["token_count"], 2000)  # 1 in + 1 out per update
        self.assertEqual(session["total_cost"], 0.1)  # 0.0001 per update
        
        # Should have entries for all 10 models
        for i in range(10):
            self.assertIn(f"model-{i}", session["models_used"])
            self.assertEqual(session["models_used"][f"model-{i}"], 100)
            

if __name__ == "__main__":
    unittest.main()
