import React, { useState, useEffect, useRef } from 'react';
import './Translation.css';

const Translation = () => {
  const [inputText, setInputText] = useState('');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages]);

  const handleSendMessage = async () => {
    if (!inputText.trim()) return;

    const newMessages = [...messages, { type: 'user', text: inputText }];
    setMessages(newMessages);
    setInputText('');
    setIsLoading(true);

    try {
      const response = await fetch('/translation/api/process-with-english-model', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ text: inputText, stream: true }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = { type: 'assistant', text: '', chinese: '' };
      let partialChunk = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        partialChunk += decoder.decode(value, { stream: true });
        let boundary = partialChunk.indexOf('\n\n');

        while(boundary !== -1) {
            const chunk = partialChunk.substring(0, boundary);
            partialChunk = partialChunk.substring(boundary + 2);

            if (chunk.startsWith('data: ')) {
                const jsonString = chunk.substring(6);
                if (jsonString === '[DONE]') {
                    break;
                }
                try {
                    const data = JSON.parse(jsonString);
                    if(data.content) {
                        if (data.content.includes('[中文翻译]:')) {
                            assistantMessage.chinese += data.content.split('[中文翻译]:')[1];
                        } else if (data.content.includes('[English Model Response]:')) {
                            // Ignore this part
                        } else if (data.content.includes('[Translating response to Chinese...]')) {
                            // Ignore this part
                        } else {
                            assistantMessage.text += data.content;
                        }
                        setMessages([...newMessages, assistantMessage]);
                    }
                } catch (e) {
                    console.error('Error parsing JSON chunk:', e);
                }
            }
            boundary = partialChunk.indexOf('\n\n');
        }
      }
    } catch (error) {
      console.error('Error:', error);
      const errorMsg = { type: 'assistant', text: 'An error occurred. Please try again.' };
      setMessages([...newMessages, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="translation-container">
      <div className="chat-window">
        {messages.map((msg, index) => (
          <div key={index} className={`message ${msg.type}`}>
            <div className="message-content">{msg.text}</div>
            {msg.chinese && <div className="message-content chinese">{msg.chinese}</div>}
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
      </div>
    </div>
  );
};

export default Translation;
