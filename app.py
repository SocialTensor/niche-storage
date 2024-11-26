import os
import io
import json
import time
import uuid
import base64
import functools
from PIL import Image
import threading
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError
from pymongo import MongoClient
import bittensor as bt
from dotenv import load_dotenv
from pydantic import BaseModel
from fastapi import FastAPI, Request, Depends, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

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

class RequestValidator:
    REQUEST_EXPIRY_LIMIT_SECONDS = 5  # Expiry limit constant

    def __init__(self):
        # In-memory storage for used nonces (consider using Redis later)
        self.upload_used_nonces = defaultdict(dict)
        self.upload_nonce_lock = threading.Lock()  # Lock for thread-safe access
        self.store_used_nonces = defaultdict(dict)
        self.store_nonce_lock = threading.Lock()  # Lock for thread-safe access

        self.metagraph = bt.subtensor("finney").metagraph(23)
        threading.Thread(target=self.sync_metagraph_periodically, daemon=True).start()

    def sync_metagraph_periodically(self) -> None:
        while True:
            print("Syncing metagraph", flush=True)
            self.metagraph.sync(subtensor=self.subtensor, lite=True)
            time.sleep(60 * 10)

    def _timestamp_check(self, received_time_ns):
        received_time_ns = int(received_time_ns)
        current_time_ns = time.time_ns()
        time_difference_seconds = (current_time_ns - received_time_ns) / 1e9  # Convert nanoseconds to seconds

        if time_difference_seconds > self.REQUEST_EXPIRY_LIMIT_SECONDS:
            raise HTTPException(status_code=400, detail="Request expired")

        return received_time_ns, current_time_ns

    async def validate_upload_request(self, request: Request):
        body = await request.json()

        # Ensure required fields are in the request body
        if "metadata" not in body or not all(field in body for field in ["nonce", "signature"]):
            raise HTTPException(status_code=400, detail="Missing required fields in request")

        # Ensure validator_uid is in the metadata
        if "validator_uid" not in body["metadata"]:
            raise HTTPException(status_code=400, detail="Missing required 'validator_uid' in metadata")

        try:
            # Perform the nonce (timestamp) check
            received_time_ns, current_time_ns = self._timestamp_check(received_time_ns=body["nonce"])
            validator_uid = body["metadata"]["validator_uid"]
            # Check if nonce is already used
            with self.upload_nonce_lock:
                if validator_uid in self.upload_used_nonces and received_time_ns in self.upload_used_nonces[validator_uid]:
                    raise HTTPException(status_code=400, detail="Replay attack detected")

                # Store nonce as used with expiration
                self.upload_used_nonces[validator_uid][received_time_ns] = current_time_ns

            # Clean up expired nonces to prevent memory bloat
            with self.upload_nonce_lock:
                for uid, nonces in list(self.upload_used_nonces.items()):
                    self.upload_used_nonces[uid] = {
                        ts: time_ns
                        for ts, time_ns in nonces.items()
                        if (current_time_ns - time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
                    }

            # Proceed with signature verification
            validator_ss58_address = self.metagraph.hotkeys[validator_uid]
            # Remove 'nonce' and 'signature' to get the original signed data structure
            original_data = {k: v for k, v in body.items() if k not in {"nonce", "signature"}}
            serialized_data = json.dumps(original_data, sort_keys=True, separators=(',', ':'))
            message = f"{serialized_data}{validator_ss58_address}{body['nonce']}"
            keypair = bt.Keypair(ss58_address=validator_ss58_address)
            
            is_verified = keypair.verify(message, body["signature"])
        except (ValueError, KeyError, IndexError):
            is_verified = False

        if not is_verified:
            raise HTTPException(status_code=400, detail="Cannot verify validator")

    async def validate_store_request(self, request: Request):
        body = await request.json()

        # Ensure required fields are in the request body
        if  not all(field in body for field in ["uid", "nonce", "signature"]):
            raise HTTPException(status_code=400, detail="Missing required fields in request")

        try:
            # Perform the nonce (timestamp) check
            received_time_ns, current_time_ns = self._timestamp_check(received_time_ns=body["nonce"])
            validator_uid = body["uid"]
            # Check if nonce is already used
            with self.store_nonce_lock:
                if validator_uid in self.store_used_nonces and received_time_ns in self.store_used_nonces[validator_uid]:
                    raise HTTPException(status_code=400, detail="Replay attack detected")

                # Store nonce as used with expiration
                self.store_used_nonces[validator_uid][received_time_ns] = current_time_ns

            # Clean up expired nonces to prevent memory bloat
            with self.store_nonce_lock:
                for uid, nonces in list(self.store_used_nonces.items()):
                    self.store_used_nonces[uid] = {
                        ts: time_ns
                        for ts, time_ns in nonces.items()
                        if (current_time_ns - time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
                    }

            # Proceed with signature verification
            validator_ss58_address = self.metagraph.hotkeys[validator_uid]
            # Remove 'nonce' and 'signature' to get the original signed data structure
            original_data = {k: v for k, v in body.items() if k not in {"nonce", "signature"}}
            serialized_data = json.dumps(original_data, sort_keys=True, separators=(',', ':'))
            message = f"{serialized_data}{validator_ss58_address}{body['nonce']}"
            keypair = bt.Keypair(ss58_address=validator_ss58_address)
            
            is_verified = keypair.verify(message, body["signature"])
        except (ValueError, KeyError, IndexError):
            is_verified = False

        if not is_verified:
            raise HTTPException(status_code=400, detail="Cannot verify validator")


### Suggestion for later expansion, need more code review
# class RequestValidator:
#     REQUEST_EXPIRY_LIMIT_SECONDS = 5  # Expiry limit constant
#     metagraph = bt.subtensor("finney").metagraph(23)

#     def __init__(self):
#         # In-memory storage for used nonces (consider using Redis later)
#         self.used_nonces = {
#             "upload": defaultdict(dict),
#             "store": defaultdict(dict),
#         }
#         self.nonce_locks = {
#             "upload": Lock(),
#             "store": Lock(),
#         }

#     def _timestamp_check(self, received_time_ns):
#         received_time_ns = int(received_time_ns)
#         current_time_ns = time.time_ns()
#         time_difference_seconds = (current_time_ns - received_time_ns) / 1e9  # Convert nanoseconds to seconds

#         if time_difference_seconds > self.REQUEST_EXPIRY_LIMIT_SECONDS:
#             raise HTTPException(status_code=400, detail="Request expired")

#         return received_time_ns, current_time_ns

#     def _nonce_replay_check(self, nonce, uid, endpoint):
#         """Check for replay attacks and clean up expired nonces."""
#         current_time_ns = time.time_ns()
#         lock = self.nonce_locks[endpoint]
#         used_nonces = self.used_nonces[endpoint]

#         with lock:
#             if uid in used_nonces and nonce in used_nonces[uid]:
#                 raise HTTPException(status_code=400, detail="Replay attack detected")
#             # Store the nonce
#             used_nonces[uid][nonce] = current_time_ns

#             # Clean up expired nonces
#             for validator_uid, nonces in list(used_nonces.items()):
#                 used_nonces[validator_uid] = {
#                     ts: ts_time_ns
#                     for ts, ts_time_ns in nonces.items()
#                     if (current_time_ns - ts_time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
#                 }

#     def _verify_signature(self, body, serialized_data, validator_uid, endpoint):
#         """Verify the signature."""
#         validator_ss58_address = self.metagraph.hotkeys[validator_uid]
#         message = f"{serialized_data}{validator_ss58_address}{body['nonce']}"
#         keypair = bt.Keypair(ss58_address=validator_ss58_address)
#         return keypair.verify(message, body["signature"])

#     async def _validate_request(self, request: Request, endpoint: str, required_fields: list, uid_field: str):
#         """Common validation logic for all endpoints."""
#         body = await request.json()

#         # Ensure required fields are in the request body, supporting nested fields
#         for field in required_fields:
#             try:
#                 # Try to access the field, possibly nested
#                 _ = self._get_nested_data(body, field)
#             except KeyError:
#                 raise HTTPException(status_code=400, detail=f"Missing required field '{field}' in request")

#         try:
#             # Extract UID using the potentially nested field path
#             validator_uid = self._get_nested_data(body, uid_field)

#             # Perform the nonce (timestamp) check
#             received_time_ns, _ = self._timestamp_check(received_time_ns=body["nonce"])
#             self._nonce_replay_check(received_time_ns, validator_uid, endpoint)

#             # Remove 'nonce' and 'signature' to get the original signed data structure
#             original_data = {k: v for k, v in body.items() if k not in {"nonce", "signature"}}
#             serialized_data = json.dumps(original_data, sort_keys=True, separators=(',', ':'))

#             # Verify the signature
#             is_verified = self._verify_signature(body, serialized_data, validator_uid, endpoint)
#         except (ValueError, KeyError, IndexError):
#             is_verified = False

#         if not is_verified:
#             raise HTTPException(status_code=400, detail="Cannot verify validator")


#     async def validate_upload_request(self, request: Request):
#         """Validate upload request."""
#         await self._validate_request(
#             request=request,
#             endpoint="upload",
#             required_fields=["nonce", "signature", "metadata.validator_uid"],
#             uid_field="metadata.validator_uid",
#         )

#     async def validate_store_request(self, request: Request):
#         """Validate store request."""
#         await self._validate_request(
#             request=request,
#             endpoint="store",
#             required_fields=["nonce", "signature", "uid"],
#             uid_field="uid",
#         )

#     def _get_nested_data(self, data, key_path):
#         """Retrieve nested data using a dot-separated key path."""
#         keys = key_path.split('.')
#         for key in keys:
#             if key in data:
#                 data = data[key]
#             else:
#                 raise KeyError(f"Key '{key}' not found in provided data.")
#         return data

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
async def upload_image(item: Base64Item, _=Depends(request_validator.validate_upload_request)):
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
async def upload_mid_journey_item(item: MidJourneyItem, _=Depends(request_validator.validate_upload_request)):
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
async def upload_llm_item(item: dict, _=Depends(request_validator.validate_upload_request)):
    # try:
    #     text_collection.insert_one(item)

    # except ClientError as e:
    #     return {"message": "Failed to upload item", "error": e}
    return {"message": "Item uploaded successfully"}
@app.post("/store_miner_info")
async def store_miner_info(item: dict, _=Depends(request_validator.validate_store_request)):
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
