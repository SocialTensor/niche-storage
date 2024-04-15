from fastapi import FastAPI, Request
import base64
import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel
import uuid
from pymongo import MongoClient
import os
from PIL import Image
from dotenv import load_dotenv
import io
from utils import get_gojourney_item

load_dotenv()

DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')


def base64_to_image(base64_string: str) -> Image:
    """Converts base64 string to PIL image."""
    decoded_string = base64.b64decode(base64_string)
    buffer = io.BytesIO(decoded_string)
    return Image.open(buffer)

def get_random_uuid():
    return str(uuid.uuid4())

class Base64Item(BaseModel):
    image: str
    metadata: dict

class MidJourneyItem(BaseModel):
    metadata: dict

class LLMItem(BaseModel):
    input_prompt: dict
    output_prompt: dict
    metadata: dict

app = FastAPI()
mongo_client = MongoClient(f'mongodb://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/')
image_collection = mongo_client['nicheimage']['images']
text_collection = mongo_client['nicheimage']['texts']
# Configure AWS S3 client
s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
BUCKET_NAME = 'nicheimage'
# Test s3 connection
print(s3.list_buckets())

@app.post("/upload-base64-item")
async def upload_image(item: Base64Item):
    try:
        image = base64_to_image(item.image)
        image_io = io.BytesIO()
        image.save(image_io, format='JPEG')
        image_io.seek(0)

        filename = f"{get_random_uuid()}.jpg"
        # Upload image to S3
        s3.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_io, ContentType='image/jpeg')
        metadata = item.metadata
        metadata.update({"key": filename, "bucket": BUCKET_NAME})
        url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{filename}"
        # Insert metadata to MongoDB
        image_collection.insert_one(metadata)

    except ClientError as e:
        return {"message": "Failed to upload image", "error": e}
    return {"message": "Image uploaded successfully"}

@app.post("/upload-mid-journey-item")
async def upload_mid_journey_item(item: MidJourneyItem):
    try:
        metadata = item.metadata
        image: Image.Image = get_gojourney_item(metadata)
        image_io = io.BytesIO()
        image.save(image_io, format='JPEG')
        image_io.seek(0)

        filename = f"{get_random_uuid()}.jpg"
        # Upload image to S3
        s3.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_io, ContentType='image/jpeg')
        metadata.update({"key": filename, "bucket": BUCKET_NAME})
        # Insert metadata to MongoDB
        image_collection.insert_one(metadata)

    except ClientError as e:
        return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}

@app.post("/upload-llm-item")
async def upload_llm_item(item: LLMItem):
    try:
        metadata = item.metadata
        metadata.update({"input_prompt": item.input_prompt, "output_prompt": item.output_prompt})
        # Insert metadata to MongoDB
        text_collection.insert_one(metadata)

    except ClientError as e:
        return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)