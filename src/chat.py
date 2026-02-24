import json
import os
import boto3
from botocore.exceptions import ClientError
from google import genai
import time
from rag import search_and_format_context
from auth import verify_token

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('TABLE_NAME'))

# Initialize Gemini client outside handler (reused between warm invocations)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def get_history(session_id):
    try:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('sessionId').eq(session_id),
            ScanIndexForward=True,  # Get oldest messages first for proper context
            Limit=10  # Limit to last 10 messages
        )
        return response.get('Items', [])
    except ClientError as e:
        print(f"Error fetching history: {e.response['Error']['Message']}")
        return []


def save_message(session_id, role, text):
    timestamp = int(time.time() * 1000)  # Current time in milliseconds
    try:
        table.put_item(
            Item={
                'sessionId': session_id,
                'timestamp': timestamp,
                'role': role,
                'content': text
            }
        )
    except ClientError as e:
        print(f"Error saving message: {e.response['Error']['Message']}")


CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
}


def handler(event, _context):
    # Handle CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # Verify JWT before any business logic
    _claims, auth_error = verify_token(event)
    if auth_error:
        return auth_error

    try:
        # 1. Parse body
        body = json.loads(event.get("body", "{}"))
        user_message = body.get("message", "")
        session_id = body.get("sessionId", "default-session")

        if not user_message:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "Message is required"})
            }
        
        # 2. Search for relevant documents and build context
        context, relevant_docs = search_and_format_context(user_message)
        
        # 3. Create enhanced prompt with context
        enhanced_message = user_message
        if context:
            enhanced_message = f"""Use the following document excerpts to answer the question. If the answer isn't in the documents, say so.

    {context}

    Question: {user_message}

    Answer:"""
        else:
            # No context found, just use the user's message directly (let LLM answer freely)
            enhanced_message = user_message
        
        # 4. Get conversation history
        history_items = get_history(session_id)
        chat_history = []
        for item in history_items:
            role = "user" if item['role'] == 'user' else "model"
            chat_history.append({
                "role": role,
                "parts": [{"text": item['content']}]
            })

        # 6. Create chat session with history and send enhanced message
        response = client.models.generate_content(
            model='models/gemini-2.5-flash',
            contents=chat_history + [{"role": "user", "parts": [{"text": enhanced_message}]}]
        )
        ai_response = response.text

        # 7. Save user message and AI response to DynamoDB
        save_message(session_id, "user", user_message)
        save_message(session_id, "assistant", ai_response)

        # 8. Return JSON response with sources
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
            "headers": CORS_HEADERS,
            "body": json.dumps(response_body)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)})
        }