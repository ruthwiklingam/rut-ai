# RAG (Retrieval-Augmented Generation) Implementation Guide

## 📋 Overview

This document explains how RAG (Retrieval-Augmented Generation) is implemented in the Ruth AI chatbot. RAG combines document retrieval with AI generation to answer questions based on your uploaded PDF documents.

## 🔄 RAG Workflow

```
1. User uploads PDF to S3
   ↓
2. Ingest Lambda: Extract text → Create embeddings → Store in Pinecone
   ↓
3. User asks question
   ↓
4. Chat Lambda: Convert question to embedding → Search Pinecone → Retrieve relevant chunks
   ↓
5. Pass question + context to Gemini → Generate answer
   ↓
6. Return answer with sources
```

---

## Part 1: Document Ingestion (ingest.py)

### Step 1: Initialize Services

```python
import json
import os
import io
import boto3
from google import genai
from pinecone import Pinecone
from pypdf import PdfReader

# Initialize services outside handler for reuse across invocations
s3 = boto3.client('s3')
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index(os.environ.get("PINECONE_INDEX"))
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
```

**Why outside handler?**
- AWS Lambda reuses execution environments
- Services persist across invocations
- Faster subsequent executions

---

### Step 2: Create Embedding Function

```python
def get_embedding(text):
    """Generate vector embedding using Gemini"""
    clean_text = text.replace("\n", " ")
    # Use embed_content with correct structure
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=[clean_text]
    )
    return response.embeddings[0].values
```

**Key Points:**
- Model: `gemini-embedding-001` (outputs 3072-dimensional vectors)
- Input: Plain text string
- Output: List of floats representing semantic meaning
- Preprocessing: Replace newlines with spaces for better embedding quality

---

### Step 3: Download PDF from S3

```python
def handler(event, context):
    try:
        # Get file info from S3 event
        record = event['Records'][0]
        bucket_name = record['s3']['bucket']['name']
        file_key = record['s3']['object']['key']

        print(f"Processing file: {file_key} from bucket: {bucket_name}")

        # Download file from S3
        response = s3.get_object(Bucket=bucket_name, Key=file_key)
        file_content = response['Body'].read()
```

**S3 Event Trigger:**
- Automatically invoked when PDF uploaded to S3
- Event contains bucket name and file key
- Downloads entire file into memory

---

### Step 4: Extract Text from PDF

```python
        # Extract text from PDF
        pdf_file = io.BytesIO(file_content)
        reader = PdfReader(pdf_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
```

**Text Extraction:**
- `io.BytesIO()`: Wraps bytes as file-like object
- `PdfReader`: Parses PDF structure
- Iterates all pages and concatenates text

---

### Step 5: Split Text into Chunks

```python
        # Split Text into Chunks
        # Gemini embedding limit is ~2048 tokens
        chunk_size = 1000
        chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
        
        print(f"Extracted {len(full_text)} characters. Split into {len(chunks)} chunks.")
```

**Why chunking?**
1. Embedding models have token limits
2. Smaller chunks = more precise search results
3. Better context isolation

**Chunking Strategy:**
- Fixed size: 1000 characters
- No overlap (could be improved)
- Simple list comprehension

---

### Step 6: Generate Embeddings & Store in Pinecone

```python
        # Generate Embeddings & Upsert to Pinecone
        vectors = []
        for i, chunk in enumerate(chunks):
            vector_id = f"{file_key}_chunk_{i}"
            embedding = get_embedding(chunk)
            
            # Metadata allows filtering and displaying context
            metadata = {
                "text": chunk,
                "source": file_key,
                "chunk_index": i
            }
            
            vectors.append((vector_id, embedding, metadata))

        # Batch upsert (more efficient than one-by-one)
        if vectors:
            index.upsert(vectors=vectors)
            print(f"Successfully indexed {len(vectors)} chunks for {file_key}")
```

**Pinecone Structure:**
- **Vector ID**: Unique identifier (`filename.pdf_chunk_0`)
- **Embedding**: 3072-dimensional vector
- **Metadata**: Original text, source file, chunk position

**Why store metadata?**
- Retrieve original text to show users
- Filter by specific documents
- Maintain ordering for context

---

### Step 7: Error Handling

```python
        return {
            "statusCode": 200,
            "body": json.dumps(f"Successfully processed {file_key}")
        }

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        # Return 200 to prevent infinite S3 retries
        return {
            "statusCode": 200, 
            "body": json.dumps(f"Failed to process: {str(e)}")
        }
```

**Error Strategy:**
- Returns 200 even on failure
- Prevents S3 infinite retry loops (for corrupted PDFs)
- Logs error to CloudWatch for debugging

---

## Part 2: RAG Search Module (rag.py)

All vector search logic lives in a dedicated `rag.py` module imported by `chat.py`. This keeps `chat.py` focused on request handling and conversation management.

### Step 1: Initialize Services

```python
import os
from google import genai
from pinecone import Pinecone

# Initialize Gemini client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Initialize Pinecone
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index(os.environ.get("PINECONE_INDEX"))
```

---

### Step 2: Embedding Function

```python
def get_embedding(text):
    """Generate vector embedding for search queries"""
    clean_text = text.replace("\n", " ")
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=[clean_text]
    )
    return response.embeddings[0].values
```

**Critical:** Must use the **same model** as ingestion!
- Documents embedded with: `gemini-embedding-001`
- Queries embedded with: `gemini-embedding-001`
- Different models = incompatible vector spaces

---

### Step 3: Search Pinecone for Relevant Documents

```python
def search_documents(query, top_k=3):
    """Search Pinecone for relevant document chunks"""
    try:
        query_embedding = get_embedding(query)
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True
        )
        contexts = []
        for match in results.matches:
            if match.metadata and 'text' in match.metadata:
                contexts.append({
                    'text': match.metadata['text'],
                    'source': match.metadata.get('source', 'unknown'),
                    'score': match.score
                })
        return contexts
    except Exception as e:
        print(f"Error searching documents: {str(e)}")
        return []
```

**How Vector Search Works:**
1. Convert user question to embedding (3072 dimensions)
2. Pinecone finds vectors with highest cosine similarity
3. Returns top 3 most relevant chunks with scores
4. Includes metadata (original text, source file)

**Similarity Score:**
- Cosine similarity: -1 to 1
- Higher = more relevant
- Only chunks scoring ≥ 0.7 are passed to Gemini as context

---

### Step 4: Format Context with Threshold Filtering

```python
def search_and_format_context(user_message, similarity_threshold=0.7):
    """Search for relevant documents and format them as context."""
    all_docs = search_documents(user_message, top_k=3)

    # Filter documents that meet the similarity threshold
    relevant_docs = [doc for doc in all_docs if doc['score'] >= similarity_threshold]

    context = ""
    if relevant_docs:
        context = "\n\nRelevant document excerpts:\n"
        for i, doc in enumerate(relevant_docs, 1):
            context += f"\n[{i}] From {doc['source']} (relevance: {doc['score']:.2f}):\n{doc['text']}\n"

    return context, relevant_docs
```

**Why a threshold?**
Without filtering, low-relevance chunks add noise to the prompt. Chunks below 0.7 are excluded — if no chunk meets the threshold, `chat.py` falls back to answering from Gemini's general knowledge rather than forcing a hallucinated "document" answer.

---

## Part 3: Question Answering (chat.py)

`chat.py` handles HTTP requests, JWT auth, conversation memory, and orchestration. RAG search is delegated entirely to `rag.py`.

### Step 1: Initialize Services

```python
import json
import os
import boto3
from botocore.exceptions import ClientError
from google import genai
import time
from rag import search_and_format_context
from auth import verify_token

# Initialize DynamoDB for conversation history
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('TABLE_NAME'))

# Initialize Gemini client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
```

**Two Systems (Pinecone is handled by rag.py):**
1. **DynamoDB**: Stores conversation history per session
2. **Gemini**: Generates AI responses

---

### Step 2: Authenticate & Search Documents

Every request is protected by JWT verification before any business logic runs:

```python
def handler(event, _context):
    # Handle CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # Verify Cognito ID token
    _claims, auth_error = verify_token(event)
    if auth_error:
        return auth_error

    body = json.loads(event.get("body", "{}"))
    user_message = body.get("message", "")
    session_id = body.get("sessionId", "default-session")

    # Search relevant docs and build context string
    context, relevant_docs = search_and_format_context(user_message)
```

**Auth flow:** `verify_token` checks the `Authorization: Bearer <id_token>` header, fetches Cognito's public JWKS (cached per container), and validates the RS256 signature. A 401 is returned immediately if the token is missing, invalid, or expired.

---

### Step 3: Create Enhanced Prompt with Context

```python
        enhanced_message = user_message
        if context:
            enhanced_message = f"""Use the following document excerpts to answer the question. If the answer isn't in the documents, say so.

{context}

Question: {user_message}

Answer:"""
```

**Prompt Engineering:**
- Instructs Gemini to use provided documents
- Tells it to admit when answer isn't in docs
- Provides clear structure: Context → Question → Answer
- Falls back to `user_message` directly if no relevant docs passed the 0.7 threshold

---

### Step 4: Get Conversation History

```python
        # Get conversation history from DynamoDB
        history_items = get_history(session_id)
        chat_history = []
        for item in history_items:
            role = "user" if item['role'] == 'user' else "model"
            chat_history.append({
                "role": role,
                "parts": [{"text": item['content']}]
            })
```

**Conversation Memory:**
- Retrieves last 10 messages from DynamoDB
- Maintains context across multiple turns
- Formats for Gemini API structure

---

### Step 5: Generate AI Response

```python
        # Create chat session with history and send enhanced message
        response = client.models.generate_content(
            model='models/gemini-2.5-flash',
            contents=chat_history + [{"role": "user", "parts": [{"text": enhanced_message}]}]
        )
        ai_response = response.text
```

**Generation:**
- Model: `gemini-2.5-flash` (fast, capable)
- Input: Conversation history + enhanced prompt with context
- Output: AI-generated answer based on documents

---

### Step 6: Save Messages & Return Response

```python
        # Save to DynamoDB
        save_message(session_id, "user", user_message)
        save_message(session_id, "assistant", ai_response)

        # Return response with sources
        response_body = {
            "response": ai_response,
            "sessionId": session_id
        }
        
        # Include sources if documents were found
        if relevant_docs:
            response_body["sources"] = [
                {"source": doc['source'], "score": doc['score']} 
                for doc in relevant_docs
            ]
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response_body)
        }
```

**Response Structure:**
```json
{
  "response": "Based on the document, XYZ...",
  "sessionId": "test-123",
  "sources": [
    {"source": "sample.pdf", "score": 0.89},
    {"source": "doc2.pdf", "score": 0.76}
  ]
}
```

---

## 🔧 Configuration Requirements

### Pinecone Index Setup

```python
# Required Configuration:
Name: "ruth-documents"
Dimensions: 3072  # Must match gemini-embedding-001
Metric: cosine
Cloud: AWS
Region: us-east-1 (match Lambda region for low latency)
```

### Environment Variables

```bash
# Ingest Lambda:
GEMINI_API_KEY=your-google-ai-api-key
PINECONE_API_KEY=your-pinecone-api-key
PINECONE_INDEX=ruth-documents

# Chat Lambda (all of the above, plus):
TABLE_NAME=your-dynamodb-table-name
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=XXXXXXXXXXXXXXXXXXXXXXXXXX
COGNITO_REGION=us-east-1

# Upload Lambda:
BUCKET_NAME=your-s3-bucket-name
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=XXXXXXXXXXXXXXXXXXXXXXXXXX
COGNITO_REGION=us-east-1
```

All values are set automatically by SST at deploy time. The Cognito IDs are emitted as stack outputs after `npx sst deploy`.

---

## 📊 RAG Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     UPLOAD PIPELINE                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Browser: POST /upload (Auth: Bearer <id_token>)            │
│           { filename, contentType }                          │
│                        ↓                                     │
│  Upload Lambda: generate_presigned_url() → return URL       │
│                        ↓                                     │
│  Browser: PUT file binary directly to S3 (no Lambda)        │
│                        ↓                                     │
│  S3 object_created → triggers Ingest Lambda                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     INGESTION PIPELINE                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  S3 Event → Ingest Lambda                                    │
│                        ↓                                     │
│              Extract Text (pypdf)                            │
│                        ↓                                     │
│         Split into 1000-char chunks                          │
│                        ↓                                     │
│    Generate embeddings (gemini-embedding-001)                │
│                        ↓                                     │
│    Store vectors + metadata in Pinecone                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      QUERY PIPELINE                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Browser: POST /chat (Auth: Bearer <id_token>)              │
│                        ↓                                     │
│  chat.py: verify_token() → 401 if invalid                   │
│                        ↓                                     │
│  rag.py: search_and_format_context()                        │
│    → embed query (gemini-embedding-001)                      │
│    → Pinecone similarity search (top_k=3)                    │
│    → filter score ≥ 0.7                                      │
│    → format context string                                   │
│                        ↓                                     │
│  Build enhanced prompt (context + question)                  │
│                        ↓                                     │
│  Load conversation history (DynamoDB, last 10 msgs)         │
│                        ↓                                     │
│  Gemini: generate_content(history + enhanced_prompt)        │
│                        ↓                                     │
│  Save user + AI messages to DynamoDB                        │
│                        ↓                                     │
│  Return { response, sessionId, sources? }                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🧪 Testing Your RAG System

> All HTTP endpoints require `Authorization: Bearer <id_token>`. Obtain an ID token by signing in via the Vue frontend or directly with the Cognito SDK.

### 1. Upload a PDF (Two-Step via Pre-Signed URL)

**Step 1 — Get a pre-signed S3 URL:**
```bash
curl -X POST https://your-upload-lambda-url.com/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <id_token>" \
  -d '{"filename": "sample.pdf", "contentType": "application/pdf"}'
# Returns: { "uploadUrl": "https://s3.amazonaws.com/...", "key": "<uuid>.pdf" }
```

**Step 2 — PUT the file directly to S3:**
```bash
curl -X PUT "<uploadUrl>" \
  -H "Content-Type: application/pdf" \
  --data-binary @sample.pdf
```

This bypasses Lambda's 6 MB payload limit entirely.

### 2. Verify Ingestion Logs

```bash
aws logs tail /aws/lambda/ruth-ai-dev-IngestFn \
  --profile awsdev --region us-east-1 --since 5m
```

Look for: `Successfully indexed X chunks for <uuid>.pdf`

### 3. Check Pinecone Stats

```python
import os
from pinecone import Pinecone

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
index = pc.Index("ruth-documents")
stats = index.describe_index_stats()
print(f"Total vectors: {stats.total_vector_count}")
```

### 4. Ask Questions

```bash
curl -X POST https://your-chat-lambda-url.com/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <id_token>" \
  -d '{
    "message": "What does the document say about X?",
    "sessionId": "test-123"
  }'
```

### Expected Response:

```json
{
  "response": "According to the document, X refers to...",
  "sessionId": "test-123",
  "sources": [
    {"source": "sample.pdf", "score": 0.87}
  ]
}
```

---

## 🚀 Performance Optimization Tips

### 1. Chunking Strategy
```python
# Current: Fixed 1000 chars
# Better: Sentence-aware chunking
def smart_chunk(text, target_size=1000, overlap=100):
    sentences = text.split('. ')
    # Create chunks respecting sentence boundaries
    # Add overlap for context preservation
```

### 2. Caching Embeddings
```python
# Cache frequently asked questions
embedding_cache = {}

def get_embedding_cached(text):
    if text in embedding_cache:
        return embedding_cache[text]
    embedding = get_embedding(text)
    embedding_cache[text] = embedding
    return embedding
```

### 3. Batch Processing
```python
# Process multiple queries in parallel
from concurrent.futures import ThreadPoolExecutor

def batch_search(queries, top_k=3):
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(
            lambda q: search_documents(q, top_k), 
            queries
        ))
    return results
```

---

## 🐛 Common Issues & Solutions

### Issue 1: Empty Search Results
**Problem**: `relevant_docs` is always empty

**Solutions:**
1. Verify Pinecone index has vectors:
   ```python
   stats = index.describe_index_stats()
   print(stats)  # Check total_vector_count > 0
   ```

2. Check dimension mismatch:
   - Index dimensions must be 3072
   - Both ingest and chat use same model

3. Test direct Pinecone query:
   ```python
   # Use a known vector from database
   results = index.query(vector=[0.1]*3072, top_k=10)
   ```

### Issue 2: Poor Relevance Scores
**Problem**: Retrieved chunks not relevant (scores < 0.5)

**Solutions:**
1. Improve chunking (sentence boundaries)
2. Add metadata filters
3. Increase top_k to retrieve more candidates
4. Clean PDF text before embedding

### Issue 3: Hallucination
**Problem**: AI makes up answers not in documents

**Solutions:**
1. Strengthen prompt instructions
2. Add system message:
   ```python
   system_prompt = "You are a helpful assistant that ONLY answers based on provided documents. If unsure, say 'I don't have that information.'"
   ```

---

## 📈 Monitoring & Metrics

### Key Metrics to Track

1. **Ingestion Success Rate**
   ```python
   successful_ingests / total_uploads
   ```

2. **Average Relevance Score**
   ```python
   avg_score = sum(doc['score'] for doc in relevant_docs) / len(relevant_docs)
   ```

3. **Query Latency**
   ```python
   # Breakdown:
   # - Embedding generation: ~100-200ms
   # - Pinecone search: ~50-100ms
   # - Gemini generation: ~1-3s
   ```

4. **Cost Per Query**
   ```python
   # Gemini API: $0.00015 per 1K tokens
   # Pinecone: Based on index size and queries
   # Lambda: $0.20 per 1M requests + compute
   ```

---

## 🎯 Summary

Your RAG system:
1. ✅ Uploads files via pre-signed S3 URL (bypasses Lambda 6 MB limit)
2. ✅ Ingests PDFs and creates searchable embeddings
3. ✅ Protects all endpoints with Cognito JWT authentication
4. ✅ Searches documents using vector similarity with a 0.7 threshold
5. ✅ Retrieves relevant context for user questions
6. ✅ Generates grounded answers with source citations
7. ✅ Maintains conversation history per session
8. ✅ Vue 3 frontend with sign-in / sign-up / confirm flow

**Next steps for improvement:**
- Add document filtering by type/date
- Implement hybrid search (keyword + vector)
- Add citation highlighting in the frontend
- Add multi-modal support (images, tables in PDFs)
- Implement chunking with sentence-boundary overlap
