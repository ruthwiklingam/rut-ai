import os
from google import genai
from pinecone import Pinecone

# Initialize Gemini client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Initialize Pinecone
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index(os.environ.get("PINECONE_INDEX"))


def get_embedding(text):
    """Generate vector embedding for search queries"""
    clean_text = text.replace("\n", " ")
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=[clean_text]
    )
    return response.embeddings[0].values


def search_documents(query, top_k=3):
    """Search Pinecone for relevant document chunks"""
    try:
        query_embedding = get_embedding(query)
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True
        )
        
        # Extract text from results
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
