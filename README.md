AutoSearch-LLM
Temporal-Aware LLM Router with Automatic Web Grounding
🚨 Problem

Large Language Models suffer from knowledge cutoff blindness.
They confidently answer time-sensitive questions using outdated training data.

Example:

Asking in 2026 about a 2025 release

Model answers using 2022 information

Only correct after forced web search

Users must manually request web search — this is broken UX.

💡 Solution

AutoSearch-LLM is a lightweight routing layer that:

Detects if a query requires up-to-date information

Automatically triggers web search when necessary

Forces the LLM to answer using only verified live sources

Returns grounded answers with citations

No retraining. Tool-augmented architecture with async retrieval.

🧠 Architecture

User Query
↓
Temporal Classifier
↓
If time-sensitive → URL Discovery (Serper API)
↓
Async Scrape + Readability Extraction
↓
Chunking + Ranking (grounding sources)
↓
Grounded Answer Generator (OpenAI)
↓
Final Response (with sources)

⚙️ Features

Temporal query classification

Automatic web search routing (time-sensitive -> grounding)

Async scraping + readability-based content extraction

Chunking + lexical relevance ranking (diversity-aware)

Source-grounded answer generation

REST API (FastAPI)

Benchmark evaluation script

📊 Evaluation

Tested on mixed time-sensitive and timeless queries.

Routing Accuracy: 80% (4/5 correct decisions)

Demonstrates measurable improvement in handling post-cutoff queries.

🚀 How to Run

1. Install dependencies
   pip install -r requirements.txt
2. Add API keys

Create a `.env`:

OPENAI_API_KEY=your_key
SERPER_API_KEY=your_key

3. Run pipeline
python pipeline.py
4. Run API
uvicorn api:app --reload

Visit:

http://127.0.0.1:8000/docs
🔬 Future Improvements

Confidence scoring instead of binary routing

Multi-step verification

Better temporal detection using structured heuristics

Larger evaluation dataset
