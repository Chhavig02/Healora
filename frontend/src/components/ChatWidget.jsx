import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../context/useAuth';
import { api } from '../lib/api';
import Alert from './ui/Alert';
import ConditionCard from './ui/ConditionCard';
import MessageBubble from './ui/MessageBubble';

// Generic symptom starters — never a disease/condition name, so this can't
// be read as a pre-baked "diagnosis" list.
const QUICK_PROMPTS = ['I have a fever', 'I have a headache', 'I have a cough', 'I have stomach pain'];

export default function ChatWidget({ open, onClose }) {
  const { token } = useAuth();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [answers, setAnswers] = useState([]);
  const [convState, setConvState] = useState(null);
  const [currentStep, setCurrentStep] = useState(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = async (text, val) => {
    const msg = text || input;
    if (!msg && val === undefined) return;
    setInput('');
    setMessages((p) => [...p, { sender: 'user', text: val !== undefined ? (val ? 'Yes' : 'No') : msg }]);
    setLoading(true);
    let ua = [...answers];
    if (val !== undefined && currentStep?.raw_symptom) ua.push([currentStep.raw_symptom, val]);
    setAnswers(ua);

    try {
      const d = await api.chat(msg, ua, token, convState);
      if (d.answers) setAnswers(d.answers);
      if (d.state !== undefined) setConvState(d.state);

      if (d.emergency) {
        setMessages((p) => [...p, { sender: 'bot', type: 'emergency', text: d.message }]);
        setAnswers([]);
        setConvState(null);
        setCurrentStep(null);
        setLoading(false);
        return;
      }

      if (d.message) setMessages((p) => [...p, { sender: 'bot', text: d.message }]);
      if (d.next_step) {
        setCurrentStep(d.next_step);
        if (d.next_step.type === 'question') {
          setMessages((p) => [
            ...p,
            { sender: 'bot', text: d.next_step.symptom, opts: d.next_step.answer_mode === 'yes_no' },
          ]);
        } else if (d.next_step.type === 'result') {
          setMessages((p) => [...p, { sender: 'bot', type: 'result', data: d.next_step }]);
          // Keep `answers`/`state` — the conversation continues (follow-up
          // questions, or a genuinely new symptom later); only the pending
          // yes/no question is cleared.
          setCurrentStep(null);
        } else if (d.next_step.type === 'reset') {
          setAnswers([]);
          setConvState(null);
          setCurrentStep(null);
        }
      }
    } catch (err) {
      console.error('Chatbot Error:', err);
      setMessages((p) => [
        ...p,
        { sender: 'bot', text: '⚠️ Connection failed. Please ensure your backend is deployed and its URL is added to the VITE_API_URL environment variable.' },
      ]);
    }
    setLoading(false);
  };

  const showQuickPrompts = messages.length === 0 && !loading;

  return (
    <>
      {open && (
        <div className="chat-modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
          <div className="chat-modal" role="dialog" aria-modal="true" aria-label="Healora symptom chat">
            <div className="chat-modal-header">
              <div className="chat-header-info">
                <div className="ai-avatar-circle">🤖</div>
                <div>
                  <div style={{ fontWeight: 800, fontSize: '1.1rem', color: 'var(--dark)', letterSpacing: '-0.5px' }}>Healora AI</div>
                  <div className="status-indicator">
                    <span className="status-dot"></span>
                    {token ? 'Personalized · Ready to help' : 'Ready to help'}
                  </div>
                </div>
              </div>
              <button className="chat-close" onClick={onClose} aria-label="Close chat">✕</button>
            </div>
            <div className="chat-messages">
              {showQuickPrompts ? (
                <div className="chat-empty-state">
                  <div className="chat-empty-icon" aria-hidden="true">💬</div>
                  <h4>What can I help you understand?</h4>
                  <p>Describe your symptoms in your own words, or start with one of these:</p>
                  <div className="quick-prompts">
                    {QUICK_PROMPTS.map((p) => (
                      <button key={p} className="quick-prompt-btn" onClick={() => send(p)}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((m, i) => (
                  <div key={i} className={`msg-row ${m.sender}`}>
                    {m.type === 'result' ? (
                      <ConditionCard data={m.data} />
                    ) : m.type === 'emergency' ? (
                      <Alert tone="danger" icon="⚠️">{m.text}</Alert>
                    ) : (
                      <MessageBubble
                        sender={m.sender}
                        actions={
                          m.opts && (
                            <div className="opts-row">
                              <button className="opt-btn" onClick={() => send(null, true)}>✅ Yes</button>
                              <button className="opt-btn" onClick={() => send(null, false)}>❌ No</button>
                            </div>
                          )
                        }
                      >
                        {m.text}
                      </MessageBubble>
                    )}
                  </div>
                ))
              )}
              {loading && (
                <div className="msg-row bot">
                  <MessageBubble sender="bot">
                    <span className="typing-dots" aria-label="Analyzing">
                      <span></span><span></span><span></span>
                    </span>
                  </MessageBubble>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
            <form className="chat-input-row" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Describe your symptoms..."
                disabled={loading}
                aria-label="Describe your symptoms"
              />
              <button type="submit" disabled={loading} aria-label="Send message">{loading ? '…' : '→'}</button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
