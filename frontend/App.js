import React, { useState } from 'react';

function App() {
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      // Step 1: Parse the project description
      const parseRes = await fetch('http://localhost:8000/api/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description }),
      });
      if (!parseRes.ok) throw new Error('Failed to parse project description');
      const parsed = await parseRes.json();

      // Step 2: Generate cost estimate
      const estRes = await fetch('http://localhost:8000/api/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description }),
      });
      if (!estRes.ok) throw new Error('Failed to generate estimate');
      const estimate = await estRes.json();

      setResult({ parsed, estimate });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 20, fontFamily: 'sans-serif' }}>
      <h1>ScopeLens — Project Cost Estimator</h1>
      <form onSubmit={handleSubmit}>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe your project (e.g., Build a React frontend with Python backend REST API for an e-commerce platform)..."
          rows={4}
          style={{ width: '100%', padding: 10, fontSize: 14 }}
          required
        />
        <br />
        <button type="submit" disabled={loading}>
          {loading ? 'Estimating...' : 'Get Estimate'}
        </button>
      </form>

      {error && <div style={{ color: 'red', marginTop: 10 }}>Error: {error}</div>}

      {result && (
        <div style={{ marginTop: 20 }}>
          <h2>Parsed Requirements</h2>
          <p><strong>Roles:</strong> {result.parsed.roles.join(', ')}</p>
          <p><strong>Technologies:</strong> {result.parsed.technologies.join(', ')}</p>
          <p><strong>Complexity:</strong> {result.parsed.complexity}</p>
          <p><strong>Est. Duration:</strong> {result.parsed.estimated_months} months</p>

          <h2>Cost Estimate</h2>
          <p><strong>Total Cost:</strong> ${result.estimate.total_cost.toLocaleString()}</p>
          <p><strong>Timeline:</strong> {result.estimate.timeline_days} days</p>

          <h3>Breakdown</h3>
          <table border="1" cellPadding="8" style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr><th>Role</th><th>Hourly Rate</th><th>Hours</th><th>Cost</th></tr>
            </thead>
            <tbody>
              {result.estimate.breakdown.map((item, i) => (
                <tr key={i}>
                  <td>{item.role}</td>
                  <td>${item.hourly_rate}/hr</td>
                  <td>{item.total_hours}</td>
                  <td>${item.cost.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default App;