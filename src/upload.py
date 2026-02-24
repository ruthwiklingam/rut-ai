import json
import boto3
import os
import base64
import uuid
from botocore.exceptions import ClientError
from auth import verify_token

# Initialize S3 client
s3_client = boto3.client('s3')

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
        # Parse the incoming request
        body = json.loads(event.get("body", "{}"))
        
        # Get file data from the request
        file_content = body.get("file")
        filename = body.get("filename")
        content_type = body.get("contentType", "application/pdf")
        
        if not file_content or not filename:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "File content and filename are required"})
            }

        # Decode base64 file content
        try:
            file_data = base64.b64decode(file_content)
        except Exception as e:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "Invalid file encoding"})
            }
        
        # Generate unique filename to avoid conflicts
        file_extension = filename.split('.')[-1] if '.' in filename else 'pdf'
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Upload to S3
        bucket_name = os.environ.get("BUCKET_NAME")
        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=unique_filename,
            Body=file_data,
            ContentType=content_type,
            Metadata={
                'original_filename': filename
            }
        )
        
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "message": "File uploaded successfully",
                "filename": unique_filename,
                "original_filename": filename
            })
        }

    except ClientError as e:
        print(f"S3 Error: {e}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "Failed to upload file to S3"})
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)})
        }