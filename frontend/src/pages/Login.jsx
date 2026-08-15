import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../components/ui/Button';
import { useAuth } from '../context/useAuth';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || 'Login failed');
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
          <h2>Welcome back</h2>
          <p className="auth-subtext">Log in to manage your reminders and personal health history.</p>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
          </label>
          <Button size="lg" type="submit" disabled={loading}>
            {loading ? 'Logging in…' : 'Log In'}
          </Button>
          <p className="auth-switch">
            Don't have an account? <Link to="/signup">Sign up</Link>
          </p>
        </form>
      </div>
    </section>
  );
}
