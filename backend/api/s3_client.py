import boto3
from botocore.exceptions import NoCredentialsError
from botocore.config import Config
import os
from dotenv import load_dotenv

# Load env from sibling directory if not found locally
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth', '.env')
load_dotenv(env_path)

# Initialize S3 client for Backblaze B2
s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv('B2_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('B2_KEY_ID'),
    aws_secret_access_key=os.getenv('B2_APP_KEY'),
    config=Config(signature_version='s3v4')
)

BUCKET_NAME = os.getenv('B2_BUCKET_NAME')

def upload_file_to_s3(file_obj, object_name):
    """Upload a file to an S3 bucket and return the object key"""
    try:
        s3_client.upload_fileobj(file_obj, BUCKET_NAME, object_name)
        return object_name # Return the key, not the URL
    except NoCredentialsError:
        print("Credentials not available")
        return None
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return None

def get_presigned_url(object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object"""
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': BUCKET_NAME,
                                                            'Key': object_name},
                                                    ExpiresIn=expiration)
        return response
    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return None

def delete_file_from_s3(object_name):
    """Delete a file from an S3 bucket"""
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=object_name)
        return True
    except Exception as e:
        print(f"Error deleting from S3: {e}")
        return False
