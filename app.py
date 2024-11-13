from threading import Lock
from collections import defaultdict
from fastapi import FastAPI, Request, Depends, HTTPException
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
import bittensor as bt
from prometheus_fastapi_instrumentator import Instrumentator

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

class RequestValidator:
    REQUEST_EXPIRY_LIMIT_SECONDS = 5  # Expiry limit constant
    metagraph = bt.subtensor("finney").metagraph(23)

    def __init__(self):
        # In-memory storage for used nonces (consider using Redis in production)
        self.used_nonces = defaultdict(dict)
        self.nonce_lock = Lock()  # Lock for thread-safe access

    async def validate_request(self, request: Request):
        body = await request.json()

        # Ensure required fields are in the request body
        if "metadata" not in body or not all(field in body for field in ["nonce", "signature"]):
            raise HTTPException(status_code=400, detail="Missing required fields in request")

        # Ensure validator_uid is in the metadata
        if "validator_uid" not in body["metadata"]:
            raise HTTPException(status_code=400, detail="Missing required 'validator_uid' in metadata")

        # Perform the nonce (timestamp) check
        try:
            received_time_ns = int(body["nonce"])
            current_time_ns = time.time_ns()
            time_difference_seconds = (current_time_ns - received_time_ns) / 1e9  # Convert nanoseconds to seconds

            if time_difference_seconds > self.REQUEST_EXPIRY_LIMIT_SECONDS:
                raise HTTPException(status_code=400, detail="Request expired")

            validator_uid = body["metadata"]["validator_uid"]
            # Check if nonce is already used
            with self.nonce_lock:
                if validator_uid in self.used_nonces and received_time_ns in self.used_nonces[validator_uid]:
                    raise HTTPException(status_code=400, detail="Replay attack detected")

                # Store nonce as used with expiration
                self.used_nonces[validator_uid][received_time_ns] = current_time_ns

            # Clean up expired nonces to prevent memory bloat
            with self.nonce_lock:
                for uid, nonces in list(self.used_nonces.items()):
                    self.used_nonces[uid] = {
                        ts: time_ns
                        for ts, time_ns in nonces.items()
                        if (current_time_ns - time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
                    }

            # Proceed with signature verification
            validator_ss58_address = self.metagraph.hotkeys[validator_uid]
            message = f"{validator_ss58_address}{body['nonce']}"
            keypair = bt.Keypair(ss58_address=validator_ss58_address)
            is_verified = keypair.verify(message, body["signature"])
        except (ValueError, KeyError):
            is_verified = False

        if not is_verified:
            raise HTTPException(status_code=400, detail="Cannot verify validator")


# Dependency instance
request_validator = RequestValidator()

app = FastAPI()
Instrumentator().instrument(app).expose(app)

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
async def upload_image(item: Base64Item, _=Depends(request_validator.validate_request)):
    # try:
    #     image = base64_to_image(item.image)
    #     image = image.convert('RGB')
    #     image_io = io.BytesIO()
    #     image.save(image_io, format='JPEG')
    #     image_io.seek(0)

    #     filename = f"{get_random_uuid()}.jpg"
    #     # Upload image to S3
    #     s3.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_io, ContentType='image/jpeg')
    #     metadata = item.metadata
    #     metadata.update({"key": filename, "bucket": BUCKET_NAME})
    #     url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{filename}"
    #     # Insert metadata to MongoDB
    #     image_collection.insert_one(metadata)

    # except ClientError as e:
    #     return {"message": "Failed to upload image", "error": e}
    return {"message": "Image uploaded successfully"}

@app.post("/upload-go-journey-item")
async def upload_mid_journey_item(item: MidJourneyItem, _=Depends(request_validator.validate_request)):
    # try:
    #     metadata = item.metadata
    #     image: Image.Image = await get_gojourney_item(item.output)
    #     image_io = io.BytesIO()
    #     image.save(image_io, format='PNG')
    #     low_io = io.BytesIO()
    #     image.save(low_io, format='JPEG')
    #     image_io.seek(0)
    #     low_io.seek(0)

    #     filename = f"{get_random_uuid()}.png"
    #     low_filename = f"{get_random_uuid()}.jpg"
    #     # Upload image to S3
    #     s3.put_object(Bucket=BUCKET_NAME, Key=filename, Body=image_io, ContentType='image/png')
    #     s3.put_object(Bucket=BUCKET_NAME, Key=low_filename, Body=low_io, ContentType='image/jpeg')
    #     metadata.update({"key": filename, "bucket": BUCKET_NAME, "jpg_key": low_filename})
    #     # Insert metadata to MongoDB
    #     image_collection.insert_one(metadata)

    # except ClientError as e:
    #     return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}

@app.post("/upload-llm-item")
async def upload_llm_item(item: dict, _=Depends(request_validator.validate_request)):
    # try:
    #     text_collection.insert_one(item)

    # except ClientError as e:
    #     return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}
@app.post("/store_miner_info")
async def store_miner_info(item: dict):
    uid = item["uid"]
    print(uid, item.get("version", "no-version"))
    validator_collection.update_one(
        {"_id": uid},
        {"$set": item},
        upsert=True
    )

    return {"message": "Item uploaded successfully"}

@app.get("/get_miner_info")
async def get_miner_info():
    validator_info = {}
    for validator in validator_collection.find():
        try:
            uid = validator['uid']
            # for k in validator["info"]:
            #     validator["info"][k].pop("timeline_score", None)
            validator_info[uid] = {
                "info": validator["info"],
                "catalogue": validator.get("catalogue", {})
            }
        except Exception as e:
            print(e)
            print(str(validator)[:100])
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
