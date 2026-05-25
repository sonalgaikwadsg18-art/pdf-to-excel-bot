# Streamlit Secrets Setup

## For Local Dev

Create `.streamlit/secrets.toml` in the project root:

```toml
GROQ_API_KEY = "gsk_your_key_here"
```

This file is in `.gitignore` — never commit it.

## For Streamlit Cloud (deployed app)

1. Go to share.streamlit.io → your app → **Settings → Secrets**
2. Paste:
```toml
GROQ_API_KEY = "gsk_your_key_here"
```
3. Click **Save**
4. Reload the app

## API Key Limits

| Tier | Requests/Day | Requests/Min |
|------|-------------|--------------|
| Groq Free | 14,400 | 30 |

The sidebar dashboard shows remaining quota after each PDF processed.
