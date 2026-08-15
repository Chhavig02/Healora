import { useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import ChatWidget from './components/ChatWidget';
import Button from './components/ui/Button';
import RequireAuth from './context/RequireAuth';
import { useAuth } from './context/useAuth';
import Dashboard from './pages/Dashboard';
import Home from './pages/Home';
import Login from './pages/Login';
import Signup from './pages/Signup';
import './index.css';

export default function App() {
  const { user, logout } = useAuth();
  const [chatOpen, setChatOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const openChat = () => setChatOpen(true);

  return (
    <>
      {/* HEADER */}
      <header className="hdr">
        <div className="hdr-inner">
          <div className="logo-area">
            <Link className="logo-link" to="/" style={{ color: 'var(--blue)' }}>Healora</Link>
          </div>

          <div className={`nav-overlay ${mobileMenuOpen ? 'active' : ''}`} onClick={() => setMobileMenuOpen(false)}></div>
          <nav className={`main-nav ${mobileMenuOpen ? 'active' : ''}`}>
            <Link to="/" onClick={() => setMobileMenuOpen(false)}>Home</Link>
            {user ? (
              <button className="nav-link-btn" onClick={() => { openChat(); setMobileMenuOpen(false); }}>Symptom Check</button>
            ) : (
              <a href="/#how-it-works" onClick={() => setMobileMenuOpen(false)}>How it works</a>
            )}
            {user && <Link to="/dashboard" onClick={() => setMobileMenuOpen(false)}>Reminders</Link>}
            <a href="/#faq" onClick={() => setMobileMenuOpen(false)}>FAQ</a>
            {user ? (
              <>
                <Link to="/dashboard" className="nav-profile" onClick={() => setMobileMenuOpen(false)}>{user.name}</Link>
                <Button className="mobile-cta" onClick={() => { logout(); setMobileMenuOpen(false); }}>Log Out</Button>
              </>
            ) : (
              <Button className="mobile-cta" onClick={() => { openChat(); setMobileMenuOpen(false); }}>Get Started</Button>
            )}
          </nav>

          <div className="hdr-actions">
            {user ? (
              <>
                <Link className="nav-profile desktop-cta" to="/dashboard">{user.name}</Link>
                <Button className="desktop-cta" onClick={logout}>Log Out</Button>
              </>
            ) : (
              <>
                <Link className="btn-outline desktop-cta" to="/login">Log In</Link>
                <Link className="btn-pill desktop-cta" to="/signup">Get Started</Link>
              </>
            )}
            <button className="menu-toggle" onClick={() => setMobileMenuOpen(!mobileMenuOpen)} aria-label="Toggle menu">
              {mobileMenuOpen ? '✕' : '☰'}
            </button>
          </div>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Home onOpenChat={openChat} />} />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <Dashboard onOpenChat={openChat} />
            </RequireAuth>
          }
        />
      </Routes>

      {/* FOOTER */}
      <footer className="site-footer">
        <div className="section-container footer-grid">
          <div className="footer-brand">
            <div className="logo-link" style={{ fontSize: '1.4rem', fontWeight: 800 }}>Healora</div>
            <p>AI-assisted symptom guidance — educational, not a diagnosis. Always consult a licensed healthcare professional.</p>
          </div>
          <div className="footer-col">
            <h4>Platform</h4>
            <a href="/#how-it-works">How it works</a>
            <a href="/#services">What Healora Offers</a>
            <a href="/#faq">FAQ</a>
          </div>
          <div className="footer-col">
            <h4>Support</h4>
            <a href="#">Help Center</a>
          </div>
          <div className="footer-col">
            <h4>Legal</h4>
            <a href="#">Privacy Policy</a>
            <a href="#">Terms</a>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 Healora. All rights reserved.</span>
          <span>⚠️ For informational purposes only. Not a substitute for medical advice.</span>
        </div>
      </footer>

      {/* CHAT FAB */}
      {!chatOpen && <button className="chat-fab" onClick={openChat} aria-label="Open symptom chat">💬</button>}

      <ChatWidget open={chatOpen} onClose={() => setChatOpen(false)} />
    </>
  );
}
