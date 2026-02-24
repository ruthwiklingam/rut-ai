import json
import boto3
import os
import uuid
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
        body = json.loads(event.get("body", "{}"))
        filename = body.get("filename")
        content_type = body.get("contentType", "application/octet-stream")

        if not filename:
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "filename is required"}),
            }

        file_extension = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        key = f"{uuid.uuid4()}.{file_extension}"
        bucket_name = os.environ.get("BUCKET_NAME")

        # Generate a pre-signed URL so the browser can PUT the file directly to S3.
        # This avoids the 6 MB Lambda payload limit entirely.
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket_name,
                "Key": key,
                "ContentType": content_type,
                "Metadata": {"original_filename": filename},
            },
            ExpiresIn=300,  # 5 minutes
        )

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({"uploadUrl": presigned_url, "key": key}),
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
