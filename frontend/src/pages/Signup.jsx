import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../components/ui/Button';
import { useAuth } from '../context/useAuth';

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await signup(name, email, password);
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="auth-split">
      <div className="auth-split-brand">
        <Link to="/" className="auth-split-logo">Healora</Link>
        <h1>Understand your health, one symptom at a time.</h1>
        <ul className="auth-split-benefits">
          <li><span aria-hidden="true">✓</span> AI-assisted symptom guidance</li>
          <li><span aria-hidden="true">✓</span> Private history tied to your account</li>
          <li><span aria-hidden="true">✓</span> Medication reminders</li>
        </ul>
      </div>

      <div className="auth-split-form-wrap">
        <form className="auth-card" onSubmit={submit}>
          <h2>Create your account</h2>
          <p className="auth-subtext">Get medication reminders and personalized health guidance from Healora.</p>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <label>
            Name
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </label>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} autoComplete="new-password" />
          </label>
          <Button size="lg" type="submit" disabled={loading}>
            {loading ? 'Creating account…' : 'Create account'}
          </Button>
          <p className="auth-switch">
            Already have an account? <Link to="/login">Log in</Link>
          </p>
        </form>
      </div>
    </section>
  );
}
