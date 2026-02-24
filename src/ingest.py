import json
import os
import io
import boto3
from google import genai
from pinecone import Pinecone
from pypdf import PdfReader

# Outside Handler Performance
s3 = boto3.client('s3')
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index(os.environ.get("PINECONE_INDEX"))
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def get_embedding(text):
    """Generate vector embedding using Gemini"""
    clean_text = text.replace("\n", " ")
    # Use embed_content with correct structure
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=[clean_text]
    )
    return response.embeddings[0].values

def handler(event, context):
    try:
        # Get info from S3 event
        record = event['Records'][0]
        bucket_name = record['s3']['bucket']['name']
        file_key = record['s3']['object']['key']

        print(f"Processing file: {file_key} from bucket: {bucket_name}")

        # Download file from S3
        response = s3.get_object(Bucket=bucket_name, Key=file_key)
        file_content = response['Body'].read()

        # Extract text from PDF
        pdf_file = io.BytesIO(file_content)
        reader = PdfReader(pdf_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"

        # 5. Split Text into Chunks (Simple Strategy)

        # Gemini embedding limit is effectively ~2048 tokens. 
        # We split by ~1000 characters to be safe and keep context tight.
        chunk_size = 1000
        chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
        
        print(f"Extracted {len(full_text)} characters. Split into {len(chunks)} chunks.")

        # 6. Generate Embeddings & Upsert to Pinecone
        vectors = []
        for i, chunk in enumerate(chunks):
            vector_id = f"{file_key}_chunk_{i}"
            embedding = get_embedding(chunk)
            
            # Metadata allows us to filter by file later if needed
            metadata = {
                "text": chunk,
                "source": file_key,
                "chunk_index": i
            }
            
            vectors.append((vector_id, embedding, metadata))

        # Batch upsert (Pinecone handles batches well)
        if vectors:
            index.upsert(vectors=vectors)
            print(f"Successfully indexed {len(vectors)} chunks for {file_key}")

        return {
            "statusCode": 200,
            "body": json.dumps(f"Successfully processed {file_key}")
        }

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        # We purposely DON'T return 500 here so S3 doesn't retry infinitely 
        # in a loop if it's a bad file. We just log the error.
        return {
            "statusCode": 200, 
            "body": json.dumps(f"Failed to process: {str(e)}")
        }