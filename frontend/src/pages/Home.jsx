import { useEffect, useState } from 'react';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import FeatureCard from '../components/ui/FeatureCard';
import SectionHeading from '../components/ui/SectionHeading';
import { api } from '../lib/api';

export default function Home({ onOpenChat }) {
  const [faqOpen, setFaqOpen] = useState(null);
  const [tip, setTip] = useState(null);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.getTip().then((d) => setTip(d.tip)).catch(() => {});
    api.getStats().then(setStats).catch(() => {});
  }, []);

  const diseaseCount = stats?.diseaseCount;
  const symptomCount = stats?.symptomCount;

  const faqs = [
    {
      q: 'What can Healora help me understand?',
      a: `Healora's knowledge base currently covers ${diseaseCount ? `${diseaseCount}+` : 'a growing number of'} conditions, matched against ${symptomCount ? `${symptomCount}` : 'hundreds of'} recognized symptoms — spanning common infections, chronic conditions, and more. It grows over time as more verified data is added.`,
    },
    {
      q: 'Is this a replacement for a real doctor?',
      a: 'No. Healora offers educational guidance to help you think through your symptoms — never a diagnosis. Always consult a qualified healthcare professional for diagnosis and treatment.',
    },
    {
      q: 'How does Healora decide what to show me?',
      a: "Every result comes from matching your symptoms against Healora's structured symptom-condition database — not a black-box percentage. Each result shows a qualitative match strength (possible, moderate, or strong) instead of a fabricated accuracy score.",
    },
    {
      q: 'Is my health data private?',
      a: 'If you chat without an account, nothing is stored. If you sign up, we keep a private history tied to your account so Healora can personalize guidance and remind you about medications — visible only to you.',
    },
    {
      q: 'How do I start a symptom check?',
      a: 'Click "Start a symptom check" or the chat bubble in the bottom-right corner and describe what you\'re feeling in your own words.',
    },
  ];

  return (
    <>
      {/* HERO */}
      <section className="hero-section">
        <div className="section-container hero-grid">
          <div className="hero-content">
            <h1>
              Understand your health.
              <br />
              <span className="text-gradient">One symptom at a time.</span>
            </h1>
            <p className="hero-subtext">
              Describe your symptoms naturally and get clear, educational guidance from Healora.
            </p>
            {tip && (
              <div className="daily-tip">
                <span className="daily-tip-label">💡 Tip of the day</span>
                <p>{tip}</p>
              </div>
            )}
            <div className="hero-btns">
              <Button size="lg" onClick={onOpenChat}>Start a symptom check →</Button>
              <Button variant="outline" size="lg" as="a" href="#how-it-works">How it works</Button>
            </div>
            <div className="hero-stat-row">
              <div className="hero-stat">
                <strong>{diseaseCount ? `${diseaseCount}+` : '—'}</strong>
                <span>Health conditions</span>
              </div>
              <div className="hero-stat">
                <strong>{symptomCount ?? '—'}</strong>
                <span>Recognized symptoms</span>
              </div>
              <div className="hero-stat">
                <strong>AI-assisted</strong>
                <span>Guidance, not a diagnosis</span>
              </div>
            </div>
          </div>

          {/* Product preview — a real representation of the actual chat experience */}
          <div className="hero-preview" aria-hidden="true">
            <div className="hero-preview-window">
              <div className="hero-preview-header">
                <div className="hero-preview-avatar">🤖</div>
                <div>
                  <strong>Healora AI</strong>
                  <span>How are you feeling?</span>
                </div>
              </div>
              <div className="hero-preview-body">
                <div className="hero-preview-bubble user">I have a fever and headache</div>
                <div className="hero-preview-label">Possible conditions</div>
                <div className="hero-preview-condition">
                  <div className="hero-preview-condition-row">
                    <strong>Common Cold</strong>
                    <Badge tone="strong">Strong match</Badge>
                  </div>
                </div>
                <div className="hero-preview-condition muted">
                  <div className="hero-preview-condition-row">
                    <strong>Acute sinusitis</strong>
                    <Badge tone="possible">Possible</Badge>
                  </div>
                </div>
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
              <span>Why Healora</span>
              <h2>An AI companion for understanding symptoms</h2>
            </div>
            <div className="honors-right">
              <p>Healora combines a structured medical knowledge base with conversational AI, so you get answers grounded in real data — explained in plain language, through a secure, private experience.</p>
            </div>
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="advantage-section" id="how-it-works">
        <div className="section-container">
          <SectionHeading tag="How Healora Helps" title="From symptoms to clarity, in three steps" />
          <div className="steps-grid">
            <div className="step-card">
              <div className="step-number">01</div>
              <h3>Describe your symptoms</h3>
              <p>Tell Healora what you're feeling in your own words — no medical jargon needed.</p>
            </div>
            <div className="step-card">
              <div className="step-number">02</div>
              <h3>Understand possible conditions</h3>
              <p>Healora matches your symptoms against a structured database and explains what it finds.</p>
            </div>
            <div className="step-card">
              <div className="step-number">03</div>
              <h3>Know what to do next</h3>
              <p>Get a clear, honest recommendation — including when to see a doctor or seek urgent care.</p>
            </div>
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section className="services-section" id="services">
        <div className="section-container">
          <SectionHeading tag="What Healora Offers" title="Everything you need to understand your symptoms" />
          <div className="feature-grid">
            <FeatureCard
              icon="💬"
              title="Symptom Support"
              description="Describe symptoms naturally and explore possible conditions grounded in real medical data."
            />
            <FeatureCard
              icon="🩺"
              title="Health Assistant"
              description="Get clear, conversational explanations of your results — not just a list of terms."
            />
            <FeatureCard
              icon="⚠️"
              title="Safety Alerts"
              description="Healora flags situations that may need urgent professional care, independent of the AI."
            />
            <FeatureCard
              icon="⏰"
              title="Medication Reminders"
              description="Create an account to keep track of your personal medication schedule."
            />
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="faq-section" id="faq">
        <div className="section-container faq-inner">
          <SectionHeading tag="FAQ" title="Everything you need to know" />
          <div className="faq-list">
            {faqs.map((f, i) => (
              <div key={i} className={`faq-item ${faqOpen === i ? 'open' : ''}`}>
                <button
                  type="button"
                  className="faq-q"
                  aria-expanded={faqOpen === i}
                  onClick={() => setFaqOpen(faqOpen === i ? null : i)}
                >
                  <span>{f.q}</span>
                  <span className="faq-icon" aria-hidden="true">{faqOpen === i ? '−' : '+'}</span>
                </button>
                {faqOpen === i && <p className="faq-a">{f.a}</p>}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA BANNER */}
      <section className="cta-banner">
        <div className="section-container cta-inner">
          <h2>Ready to understand your symptoms?</h2>
          <p>Free to try, grounded in a real medical knowledge base — no account required to get started.</p>
          <Button variant="white" size="lg" onClick={onOpenChat}>Start a symptom check →</Button>
        </div>
      </section>
    </>
  );
}
