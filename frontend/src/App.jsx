import { useState, useRef, useEffect } from 'react';
import './index.css';

export default function App() {
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState([{ sender: 'bot', text: "Hi! I'm Healora AI. Describe your symptoms and I'll help assess them." }]);
  const [input, setInput] = useState('');
  const [answers, setAnswers] = useState([]);
  const [currentStep, setCurrentStep] = useState(null);
  const [loading, setLoading] = useState(false);
  const [faqOpen, setFaqOpen] = useState(null);
  const bottomRef = useRef(null);
  const scrollerRef = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // Horizontal Mouse Wheel Scroll Logic
  const handleWheel = (e) => {
    if (scrollerRef.current) {
      e.preventDefault();
      scrollerRef.current.scrollLeft += e.deltaY;
      
      // Infinite Loop Logic
      const s = scrollerRef.current;
      if (s.scrollLeft <= 0) s.scrollLeft = s.scrollWidth / 2;
      if (s.scrollLeft >= s.scrollWidth / 2) s.scrollLeft = 1;
    }
  };

  useEffect(() => {
    const s = scrollerRef.current;
    if (s) {
      s.addEventListener('wheel', handleWheel, { passive: false });
      // Set initial scroll to middle for circular feel
      s.scrollLeft = s.scrollWidth / 4;
    }
    return () => s?.removeEventListener('wheel', handleWheel);
  }, []);

  const send = async (text, val) => {
    const msg = text || input;
    if (!msg && val === undefined) return;
    setInput('');
    setMessages(p => [...p, { sender: 'user', text: val !== undefined ? (val ? 'Yes' : 'No') : msg }]);
    setLoading(true);
    let ua = [...answers];
    if (val !== undefined && currentStep?.raw_symptom) ua.push([currentStep.raw_symptom, val]);
    setAnswers(ua);
    const BACKEND_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
    try {
      const r = await fetch(`${BACKEND_URL}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg, answers: ua }) });
      const d = await r.json();
      if (d.answers) setAnswers(d.answers);
      if (d.message) setMessages(p => [...p, { sender: 'bot', text: d.message }]);
      if (d.next_step) {
        setCurrentStep(d.next_step);
        if (d.next_step.type === 'question') setMessages(p => [...p, { sender: 'bot', text: d.next_step.symptom, opts: true }]);
        else if (d.next_step.type === 'result') { setMessages(p => [...p, { sender: 'bot', type: 'result', data: d.next_step }]); setAnswers([]); setCurrentStep(null); }
      }
    } catch { setMessages(p => [...p, { sender: 'bot', text: '⚠️ Backend not reachable. Start the Flask server.' }]); }
    setLoading(false);
  };

  const faqs = [
    { q: 'What conditions can Healora detect?', a: 'Healora is trained on 41+ diseases including heart disease, diabetes, respiratory conditions, neurological disorders, and more.' },
    { q: 'Is this a replacement for a real doctor?', a: 'No. Healora provides preliminary AI-based assessments. Always consult a qualified healthcare professional for diagnosis and treatment.' },
    { q: 'How accurate is the AI?', a: 'Our model achieves ~95% accuracy on the training dataset. Confidence scores are shown with every result.' },
    { q: 'Is my health data private?', a: 'Yes. No data is stored or tracked. Each session is completely stateless and private.' },
    { q: 'How do I start a consultation?', a: 'Click the "Start Consultation" button or the chat bubble in the bottom-right corner and describe your symptoms.' },
  ];

  return (
    <>
      {/* HEADER */}
      <header className="hdr">
        <div className="hdr-inner">
          <div className="logo-area">
            <a className="logo-link" href="#" style={{color: 'var(--blue)'}}>Healora</a>
          </div>
          <nav className="main-nav">
            <a href="#services">Home</a>
            <a href="#about">About</a>
            <a href="#testimonials">Shop</a>
            <a href="#faq">Blog</a>
            <div className="nav-dropdown">Pages ▾</div>
          </nav>
          <div className="hdr-actions">
            <div className="cart-icon">🛒<span className="cart-count">0</span></div>
            <button className="btn-pill" onClick={() => setChatOpen(true)} style={{background: 'var(--blue)'}}>Get Started</button>
          </div>
        </div>
      </header>

      {/* HERO */}
      {/* HERO SECTION */}
      <section className="hero-section">
        <div className="section-container hero-grid">
          <div className="hero-content">
            <h1>Your Partner in Health, <span className="text-gradient">Every Step</span> of the Way</h1>
            <p className="hero-subtext">Experience the future of healthcare with Healora's AI-driven diagnostics and personalized wellness plans tailored for your unique DNA.</p>
            <div className="hero-btns">
              <button className="btn-pill btn-lg" onClick={() => setChatOpen(true)}>Start Free Consultation →</button>
              <button className="btn-pill btn-lg btn-outline">Watch Demo</button>
            </div>
          </div>
          
          <div className="hero-simulation">
            {/* Double Helix DNA Animation */}
            <div className="dna-wrap">
              {[...Array(20)].map((_, i) => (
                <div key={i} className="dna-dot strand-1" style={{ '--i': i }}></div>
              ))}
              {[...Array(20)].map((_, i) => (
                <div key={i} className="dna-dot strand-2" style={{ '--i': i }}></div>
              ))}
              <div className="capsule capsule-1"></div>
              <div className="capsule capsule-2"></div>
            </div>

            {/* Floating Stats */}
            <div className="sim-badge badge-1">
              <div className="sim-line"></div>
              <div className="sim-info">
                <strong>95%</strong>
                <span>Diseases Treated</span>
              </div>
            </div>

            <div className="sim-badge badge-2">
              <div className="sim-line"></div>
              <div className="sim-info">
                <strong>100%</strong>
                <span>Commitment To Well-Being</span>
              </div>
            </div>

            <div className="sim-badge badge-3">
              <div className="sim-line"></div>
              <div className="sim-info">
                <strong>99%</strong>
                <span>Patient Satisfaction</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* WHY CHOOSE SECTION */}
      <section className="honors-section">
        <div className="section-container">
          <div className="honors-card">
            <div className="honors-left">
              <span>Why Choose Healora AI</span>
              <h2>Your trusted AI companion for healthcare assistance</h2>
            </div>
            <div className="honors-right">
              <p>From symptom checking to medical guidance and report understanding, Healora AI helps users access reliable healthcare support anytime through a secure, intelligent, and user-friendly platform.</p>
            </div>
          </div>
        </div>
      </section>

      {/* TICKER */}
      <div className="ticker-bar">
        <div className="ticker-track">
          {[...Array(4)].map((_, i) => (
            <span key={i}>
              <img src="https://images.unsplash.com/photo-1551076805-e1869033e561?w=100&q=80" alt="medical" />
              THE SCIENCE OF HEALING, THE ART OF CARE
            </span>
          ))}
        </div>
      </div>

      {/* ADVANTAGE / DASHBOARD SECTION */}
      <section className="advantage-section" id="about">
        <div className="section-container advantage-grid">
          <div className="adv-left">
            <span className="section-tag">Our Advantage</span>
            <h2>Maximizing Care Efficiency<br/>at Medical Clinics</h2>
            <p>We bring together expert care, modern tools, and patient-focused service to make every visit smooth, efficient, and effective.</p>
            <button className="btn-pill btn-lg">Appointment</button>
          </div>
          
          <div className="adv-right-grid">
            {/* Card 1: Bar Chart */}
            <div className="adv-card adv-card-1">
              <div className="bar-chart">
                {[40, 70, 50, 90, 60, 80, 45].map((h, i) => (
                  <div key={i} className="bar-wrap"><div className="bar" style={{height:`${h}%`}}></div></div>
                ))}
              </div>
              <div className="adv-card-footer">
                <strong>95%</strong> <span>of patients seen within 24 hours.</span>
              </div>
            </div>

            {/* Card 2: Line Graph */}
            <div className="adv-card adv-card-2">
              <p className="adv-card-title">Improvement in treatment effectiveness with modern equipment</p>
              <small>2015 - 2025</small>
              <div className="line-graph">
                <svg viewBox="0 0 200 60" className="chart-line">
                  <path d="M0,55 Q50,50 80,40 T150,20 T200,15" fill="none" stroke="var(--navy)" strokeWidth="2" />
                  <circle cx="200" cy="15" r="3" fill="var(--navy)" />
                  <text x="175" y="10" fontSize="8" fontWeight="800">92%</text>
                </svg>
              </div>
              <div className="heart-icon-small">💙</div>
            </div>

            {/* Card 3: Big Circle Card */}
            <div className="adv-card adv-card-big">
              <div className="circle-progress-wrap">
                <svg className="circle-svg" viewBox="0 0 100 100">
                  <circle className="circle-bg" cx="50" cy="50" r="45" />
                  <circle className="circle-fg" cx="50" cy="50" r="45" style={{strokeDasharray: '283', strokeDashoffset: '50'}} />
                </svg>
                <div className="circle-text">
                  <strong>82%</strong>
                  <p>experienced better overall well-being</p>
                </div>
              </div>
              <div className="adv-icons-stack">
                <span className="adv-icon">🏠</span>
                <span className="adv-icon">😊</span>
                <span className="adv-icon">🌿</span>
              </div>
              <div className="shop-banner">
                <div className="shop-img">💊</div>
                <div className="shop-text">
                  <p>Check out our multivitamins</p>
                  <button className="shop-btn">Shop</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES */}
      <section className="services-section" id="services">
        <div className="section-container">
          <div className="services-hdr-flex">
            <div className="services-title-area">
              <span className="section-tag">Our Services</span>
              <h2>Expert Healthcare Services<br/>Tailored to Your Well-being</h2>
            </div>
            <button className="btn-pill">See All Services</button>
          </div>
          
          <div className="services-scroller-wrap">
            <div className="services-scroller" ref={scrollerRef}>
              {[...Array(3)].map((_, i) => (
                <div key={i} style={{display:'flex', gap:'2rem'}}>
                  {[
                    { img: 'https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=600&q=80', title: 'Cardiology' },
                    { img: 'https://images.unsplash.com/photo-1559757175-5700dde675bc?w=600&q=80', title: 'Neurology' },
                    { img: 'https://images.unsplash.com/photo-1516549655169-df83a0774514?w=600&q=80', title: 'General Surgery' },
                    { img: 'https://images.unsplash.com/photo-1582719471384-894fbb16e074?w=600&q=80', title: 'Orthopedics' },
                    { img: 'https://images.unsplash.com/photo-1527613426441-4da17471b66d?w=600&q=80', title: 'Dermatology' },
                    { img: 'https://images.unsplash.com/photo-1537151608828-ea2b11777ee8?w=600&q=80', title: 'Pediatrics' },
                  ].map((s, idx) => (
                    <div key={idx} className="service-card-tilted">
                      <img src={s.img} alt={s.title} />
                      <div className="svc-label">
                        <span>{s.title}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* TESTIMONIALS */}
      <section className="testimonials-section" id="testimonials">
        <div className="section-container">
          <div className="section-header">
            <span className="section-tag">Patient Feedback</span>
            <h2>Trusted by Thousands of Patients</h2>
          </div>
          <div className="testi-grid">
            {[
              { name: 'Sophia M.', role: 'Dermatology Patient', quote: 'As a first-time user, I was impressed by how friendly and accurate the AI was. My symptom assessment was spot on!', stars: 5 },
              { name: 'Emily D.', role: 'Cardiology Patient', quote: 'Healora explained my symptoms clearly and guided me to the right specialist. The confidence scores were reassuring.', stars: 5 },
              { name: 'James R.', role: 'Diabetes Care', quote: 'I was skeptical at first, but the AI knew exactly what questions to ask. It felt like talking to a knowledgeable friend.', stars: 5 },
            ].map((t, i) => (
              <div key={i} className="testi-card">
                <div className="stars">{'★'.repeat(t.stars)}</div>
                <p>"{t.quote}"</p>
                <div className="testi-author"><div className="testi-avatar">{t.name[0]}</div><div><strong>{t.name}</strong><small>{t.role}</small></div></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="faq-section" id="faq">
        <div className="section-container faq-inner">
          <div className="section-header">
            <span className="section-tag">FAQ</span>
            <h2>Everything You Need to Know</h2>
          </div>
          <div className="faq-list">
            {faqs.map((f, i) => (
              <div key={i} className={`faq-item ${faqOpen === i ? 'open' : ''}`} onClick={() => setFaqOpen(faqOpen === i ? null : i)}>
                <div className="faq-q"><span>{f.q}</span><span className="faq-icon">{faqOpen === i ? '−' : '+'}</span></div>
                {faqOpen === i && <p className="faq-a">{f.a}</p>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA BANNER */}
      <section className="cta-banner">
        <div className="section-container cta-inner">
          <h2>Ready to Get Started?</h2>
          <p>Join thousands who trust Healora for fast, accurate, AI-powered health insights.</p>
          <button className="btn-pill btn-lg btn-white" onClick={() => setChatOpen(true)}>Start Free Consultation →</button>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="site-footer">
        <div className="section-container footer-grid">
          <div className="footer-brand">
            <div className="logo-link" style={{fontSize:'1.4rem',fontWeight:800}}>Healora ⚕️</div>
            <p>Advancing global healthcare through empathetic, precise, and accessible AI diagnostics.</p>
          </div>
          <div className="footer-col"><h4>Platform</h4><a href="#services">Services</a><a href="#about">About</a><a href="#faq">FAQ</a></div>
          <div className="footer-col"><h4>Support</h4><a href="#">Help Center</a><a href="#">Privacy Policy</a><a href="#">Terms</a></div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 Healora. All rights reserved.</span>
          <span>⚠️ For informational purposes only. Not a substitute for medical advice.</span>
        </div>
      </footer>

      {/* CHAT FAB */}
      <button className="chat-fab" onClick={() => setChatOpen(true)}>💬</button>

      {/* CHAT MODAL */}
      {chatOpen && (
        <div className="chat-modal-overlay" onClick={(e) => e.target === e.currentTarget && setChatOpen(false)}>
          <div className="chat-modal">
            <div className="chat-modal-header">
              <div className="chat-header-info">
                <div className="ai-avatar-circle">🤖</div>
                <div>
                  <div style={{fontWeight:800,fontSize:'1.1rem',color:'var(--dark)',letterSpacing:'-0.5px'}}>Healora AI</div>
                  <div className="status-indicator">
                    <span className="status-dot"></span>
                    Ready to help
                  </div>
                </div>
              </div>
              <button className="chat-close" onClick={() => setChatOpen(false)}>✕</button>
            </div>
            <div className="chat-messages">
              {messages.map((m, i) => (
                <div key={i} className={`msg-row ${m.sender}`}>
                  {m.type === 'result' ? (
                    <div className="result-card">
                      <div className="result-title">{m.data.disease}</div>
                      <p>{m.data.description}</p>
                      <div className="result-bar-wrap"><div className="result-bar" style={{width:`${m.data.confidence}%`}}></div></div>
                      <div className="result-tags"><span className="tag">Confidence: {m.data.confidence}%</span><span className={`tag ${m.data.risk>=70?'tag-danger':''}`}>Risk: {m.data.risk}%</span></div>
                    </div>
                  ) : (
                    <div className={`bubble ${m.sender}`}>
                      {m.text}
                      {m.opts && <div className="opts-row"><button className="opt-btn" onClick={() => send(null, true)}>✅ Yes</button><button className="opt-btn" onClick={() => send(null, false)}>❌ No</button></div>}
                    </div>
                  )}
                </div>
              ))}
              {loading && <div className="msg-row bot"><div className="bubble bot">Analyzing... ⏳</div></div>}
              <div ref={bottomRef} />
            </div>
            <form className="chat-input-row" onSubmit={e => { e.preventDefault(); send(); }}>
              <input value={input} onChange={e => setInput(e.target.value)} placeholder="Describe your symptoms..." disabled={loading} />
              <button type="submit" disabled={loading}>{loading ? '…' : '→'}</button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
