from fastapi import FastAPI, Request
import base64
import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel
import uuid
from pymongo import MongoClient
import os, time
from PIL import Image
from dotenv import load_dotenv
import io
from utils import get_gojourney_item

def pil_image_to_base64(image: Image) -> str:
    """Converts PIL image to base64 string."""
    image_io = io.BytesIO()
    image.save(image_io, format='PNG')
    image_io.seek(0)
    return base64.b64encode(image_io.getvalue()).decode()

load_dotenv()

DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

VALIDATOR_INFO = {}

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
    output: dict
    metadata: dict

class LLMItem(BaseModel):
    input_prompt: str
    output_prompt: dict
    metadata: dict

class MinerItem(BaseModel):
    validator_uid: int
    miner_uid: int

app = FastAPI()
mongo_client = MongoClient(f'mongodb://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/')
image_collection = mongo_client['nicheimage']['images']
text_collection = mongo_client['nicheimage']['texts']
validator_collection = mongo_client['nicheimage']['validator_infos']
# Configure AWS S3 client
s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
BUCKET_NAME = 'nicheimage-real-caption'
# Test s3 connection
print(s3.list_buckets())

@app.post("/upload-base64-item")
async def upload_image(item: Base64Item):
    try:
        image = base64_to_image(item.image)
        image = image.convert('RGB')
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

@app.post("/upload-go-journey-item")
async def upload_mid_journey_item(item: MidJourneyItem):
    try:
        metadata = item.metadata
        image: Image.Image = await get_gojourney_item(item.output)
        image_io = io.BytesIO()
        image.save(image_io, format='PNG')
        low_io = io.BytesIO()
        image.save(low_io, format='JPEG')
        image_io.seek(0)
        low_io.seek(0)

        filename = f"{get_random_uuid()}.png"
        low_filename = f"{get_random_uuid()}.jpg"
        # Upload image to S3
        s3.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_io, ContentType='image/png')
        s3.put_object(Bucket=BUCKET_NAME, Key=low_filename, Body=low_io, ContentType='image/jpeg')
        metadata.update({"key": filename, "bucket": BUCKET_NAME, "jpg_key": low_filename})
        # Insert metadata to MongoDB
        image_collection.insert_one(metadata)

    except ClientError as e:
        return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}

@app.post("/upload-llm-item")
async def upload_llm_item(item: dict):
    try:
        text_collection.insert_one(item)

    except ClientError as e:
        return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}
@app.post("/store_miner_info")
async def store_miner_info(item: dict):
    uid = item['uid']
    
    # Find the record by its _id
    record = validator_collection.find_one({"_id": uid})
    print(record["uid"], record["version"])
    print(f"Record found: {bool(record)}")
    # If the record does not exist, create it from item
    if not record:
        record = {
            "_id": uid,  # Ensure the record keeps _id
            "info": {}
        }
    
    # Update the info field while preserving existing data
    for k, v in item["info"].items():
        v.pop("timeline_score", None)  # Remove timeline_score if present
        record["info"][k] = v
        
        # Add timeline score
        dt = {
            "reward": sum(v["scores"]) / 10,
            "time": time.time()
        }
        timeline = record["info"][k].get("timeline_score", [])
        timeline.append(dt)
        record["info"][k]["timeline_score"] = timeline[-100:]  # Keep only the last 100 entries
    print(record["uid"], record["version"])
    # Update or insert the record into the collection
    result = validator_collection.replace_one(
        {"_id": uid},
        record,
        upsert=True
    )
    print(f"Matched: {result.matched_count}, Modified: {result.modified_count}")

    
    return {"message": "Item uploaded successfully"}

@app.get("/get_miner_info")
async def get_miner_info():
    validator_info = {}
    for validator in validator_collection.find():
        try:
            uid = validator['uid']
            for k in validator["info"]:
                validator["info"][k].pop("timeline_score", None)
            validator_info[uid] = {
                "info": validator["info"]
            }
        except Exception as e:
            print("get_miner_info", e)
            continue
    return validator_info

@app.post("/get_miner_timeline")
async def get_miner_timeline(item: MinerItem):
    validator_data = validator_collection.find_one({"uid": item.validator_uid})
    miner_data = validator_data["info"][str(item.miner_uid)]
    return miner_data



@app.get("/get_image/{bucket}/{key}")
async def get_image(bucket: str, key: str):
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        image = Image.open(io.BytesIO(response['Body'].read()))
        base64_image = pil_image_to_base64(image)
        return {"image": base64_image}
    except ClientError as e:
        return {"message": "Failed to get image", "error": e}
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
