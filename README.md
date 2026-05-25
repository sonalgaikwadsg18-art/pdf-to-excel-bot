# PDF to Excel Bot

Upload any PDF. AI understands document structure. Download professional Excel.

## Quick deploy (free)

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "PDF to Excel bot"
# Create repo on github.com, then:
git remote add origin https://github.com/YOUR_USER/pdf-to-excel-bot.git
git push -u origin main
```

### 2. Deploy on Streamlit Cloud
Go to share.streamlit.io -> Sign in with GitHub -> New app -> Select repo -> Deploy

### 3. Add your API key
In Streamlit Cloud dashboard: Settings -> Secrets -> Add:
```
GROQ_API_KEY = "gsk_your_key_here"
```
Get a free key at console.groq.com (no credit card needed).

## Two modes

| Mode | Key needed | Quality |
|---|---|---|
| AI Mode (default) | Groq key in Secrets | Same as manual human work |
| Basic Mode | No key | Decent rule-based extraction |

## Quota dashboard

After processing a PDF in AI mode, the sidebar shows your Groq API usage:
- Requests remaining / total (with color-coded progress bar)
- Tokens remaining
- Updates after every PDF processed

## Local dev
```bash
pip install -r requirements.txt
echo 'GROQ_API_KEY = "gsk_your_key"' > .streamlit/secrets.toml
streamlit run app.py
```
