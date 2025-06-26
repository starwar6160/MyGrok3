import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import './Translation.css';

const Translation = () => {
  const [inputText, setInputText] = useState('');
  const [messages, setMessages] = useState(() => {
    try {
      const savedMessages = localStorage.getItem('translation_messages');
      return savedMessages ? JSON.parse(savedMessages) : [];
    } catch (error) {
      console.error('Failed to load messages from local storage:', error);
      localStorage.removeItem('translation_messages'); // Clear corrupted data
      return [];
    }
  });
  const [isLoading, setIsLoading] = useState(false);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    fetch('/api/models')
      .then(res => res.json())
      .then(data => {
        setModels(data.models);
        if (data.default_model) {
          setSelectedModel(data.default_model);
        }
      })
      .catch(error => console.error('Failed to fetch models:', error));
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages]);

  // Save messages to local storage whenever they change
  useEffect(() => {
    try {
      if (messages.length === 0) {
        localStorage.removeItem('translation_messages');
      } else {
        localStorage.setItem('translation_messages', JSON.stringify(messages));
      }
    } catch (error) {
      console.error('Failed to save messages to local storage:', error);
    }
  }, [messages]);

  const handleCopyAll = () => {
    const allMessagesText = messages.map(msg => {
        let messageText = `[${msg.type === 'user' ? 'User' : 'Assistant'}]:\n${msg.text}`;
        if (msg.chinese) {
            messageText += `\n\n[Chinese Translation]:\n${msg.chinese}`;
        }
        return messageText;
    }).join('\n\n---\n\n');

    const textArea = document.createElement('textarea');
    textArea.value = allMessagesText;
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";

    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        const successful = document.execCommand('copy');
        if (successful) {
            alert('All conversation copied to clipboard!');
        } else {
            alert('Failed to copy conversation.');
        }
    } catch (err) {
        console.error('Failed to copy conversation:', err);
        alert('Failed to copy conversation.');
    }

    document.body.removeChild(textArea);
  };

  const handleNewConversation = () => {
    setMessages([]);
    setInputText('');
    // The useEffect hook will handle clearing local storage
  };

  const handleSendMessage = async () => {
    if (!inputText.trim()) return;

    const userMessage = { type: 'user', text: inputText };
    setMessages(prevMessages => [...prevMessages, userMessage]);
    const currentInput = inputText;
    setInputText('');
    setIsLoading(true);

    try {
      const response = await fetch('/translation/api/process-with-english-model', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ text: currentInput, stream: true, model: selectedModel }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      // Initialize empty assistant message
      setMessages(prevMessages => [...prevMessages, { 
        type: 'assistant', 
        text: '', 
        chinese: '',
        diagnostics: '' // New field to store cost/token statistics
      }]);
      
      let fullResponse = '';

      // Process the plaintext streaming response
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // Decode the chunk and add it to the full response
        const chunk = decoder.decode(value, { stream: true });
        fullResponse += chunk;
        
        // Check if the response contains diagnostics (after '---')
        const parts = fullResponse.split('\n\n---\n');
        const mainContent = parts[0];
        const diagnostics = parts.length > 1 ? parts[1] : '';
        
        // Update the message with the current content
        setMessages(prevMessages => {
          const lastMessageIndex = prevMessages.length - 1;
          if (lastMessageIndex < 0) return prevMessages;
          
          const lastMessage = prevMessages[lastMessageIndex];
          if (lastMessage.type !== 'assistant') return prevMessages;
          
          // Create updated message with current content
          const updatedLastMessage = { 
            ...lastMessage,
            text: mainContent,
            diagnostics: diagnostics
          };
          
          const newMessages = [...prevMessages];
          newMessages[lastMessageIndex] = updatedLastMessage;
          return newMessages;
        });
      }
      
      console.log('Translation streaming completed successfully');
      
    } catch (error) {
      console.error('Error during translation:', error);
      setMessages(prevMessages => {
        const lastMessage = prevMessages[prevMessages.length - 1];
        if (lastMessage && lastMessage.type === 'assistant' && lastMessage.text === '') {
          // Replace the empty assistant message with an error
          const updatedMessages = [...prevMessages.slice(0, -1), { 
            type: 'assistant', 
            text: 'An error occurred during translation. Please try again.', 
            chinese: '',
            diagnostics: ''
          }];
          return updatedMessages;
        }
        // Add a new error message
        return [...prevMessages, { 
          type: 'assistant', 
          text: 'An error occurred during translation. Please try again.', 
          chinese: '',
          diagnostics: ''
        }];
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="translation-container">
       <div className="header">
        <Link to="/" className="home-link">Home</Link>
        <select 
          className="model-selector"
          value={selectedModel} 
          onChange={(e) => setSelectedModel(e.target.value)}
        >
          {models.map(model => (
            <option key={model} value={model}>{model}</option>
          ))}
        </select>
      </div>
      <div className="chat-window">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.type}`}>
            <div className="message-content">{msg.text}</div>
            {msg.chinese && <div className="message-content chinese"><br />{msg.chinese}</div>}
            {msg.diagnostics && (
              <div className="message-diagnostics">
                <hr />
                <pre>{msg.diagnostics}</pre>
              </div>
            )}
          </div>
        ))}
        {isLoading && (
          <div className="message assistant">
            <div className="message-content">...</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="input-area">
        <textarea
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
          placeholder="Type your message..."
        />
        <button onClick={handleSendMessage} disabled={isLoading}>
          Send
        </button>
        <button onClick={handleCopyAll}>Copy All</button>
        <button onClick={handleNewConversation}>New Conversation</button>
      </div>
    </div>
  );
};

export default Translation;
