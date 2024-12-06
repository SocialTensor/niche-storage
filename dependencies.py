import json
import time
import threading
from collections import defaultdict

import bittensor as bt
from fastapi import Request, HTTPException


metagraph: bt.metagraph = bt.subtensor("finney").metagraph(23)

def sync_metagraph_periodically() -> None:
    while True:
        print("Syncing metagraph", flush=True)
        metagraph.sync(lite=True)
        time.sleep(60 * 10)

threading.Thread(target=sync_metagraph_periodically, daemon=True).start()

# class RequestValidator:
#     REQUEST_EXPIRY_LIMIT_SECONDS = 5  # Expiry limit constant

#     def __init__(self):
#         # In-memory storage for used nonces (consider using Redis later)
#         self.upload_used_nonces = defaultdict(dict)
#         self.upload_nonce_lock = threading.Lock()  # Lock for thread-safe access
#         self.store_used_nonces = defaultdict(dict)
#         self.store_nonce_lock = threading.Lock()  # Lock for thread-safe access

#         self.metagraph: bt.metagraph = bt.subtensor("finney").metagraph(23)
#         threading.Thread(target=self.sync_metagraph_periodically, daemon=True).start()

#     def sync_metagraph_periodically(self) -> None:
#         while True:
#             print("Syncing metagraph", flush=True)
#             self.metagraph.sync(subtensor=self.subtensor, lite=True)
#             time.sleep(60 * 10)

#     def _timestamp_check(self, received_time_ns):
#         received_time_ns = int(received_time_ns)
#         current_time_ns = time.time_ns()
#         time_difference_seconds = (current_time_ns - received_time_ns) / 1e9  # Convert nanoseconds to seconds

#         if time_difference_seconds > self.REQUEST_EXPIRY_LIMIT_SECONDS:
#             raise HTTPException(status_code=400, detail="Request expired")

#         return received_time_ns, current_time_ns

#     async def validate_upload_request(self, request: Request):
#         body = await request.json()

#         # Ensure required fields are in the request body
#         if "metadata" not in body or not all(field in body for field in ["nonce", "signature"]):
#             raise HTTPException(status_code=400, detail="Missing required fields in request")

#         # Ensure validator_uid is in the metadata
#         if "validator_uid" not in body["metadata"]:
#             raise HTTPException(status_code=400, detail="Missing required 'validator_uid' in metadata")

#         try:
#             # Perform the nonce (timestamp) check
#             received_time_ns, current_time_ns = self._timestamp_check(received_time_ns=body["nonce"])
#             validator_uid = body["metadata"]["validator_uid"]
#             # Check if nonce is already used
#             with self.upload_nonce_lock:
#                 if validator_uid in self.upload_used_nonces and received_time_ns in self.upload_used_nonces[validator_uid]:
#                     raise HTTPException(status_code=400, detail="Replay attack detected")

#                 # Store nonce as used with expiration
#                 self.upload_used_nonces[validator_uid][received_time_ns] = current_time_ns

#             # Clean up expired nonces to prevent memory bloat
#             with self.upload_nonce_lock:
#                 for uid, nonces in list(self.upload_used_nonces.items()):
#                     self.upload_used_nonces[uid] = {
#                         ts: time_ns
#                         for ts, time_ns in nonces.items()
#                         if (current_time_ns - time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
#                     }

#             # Proceed with signature verification
#             validator_ss58_address = self.metagraph.hotkeys[validator_uid]
#             # Remove 'nonce' and 'signature' to get the original signed data structure
#             original_data = {k: v for k, v in body.items() if k not in {"nonce", "signature"}}
#             serialized_data = json.dumps(original_data, sort_keys=True, separators=(',', ':'))
#             message = f"{serialized_data}{validator_ss58_address}{body['nonce']}"
#             keypair = bt.Keypair(ss58_address=validator_ss58_address)
            
#             is_verified = keypair.verify(message, body["signature"])
#         except (ValueError, KeyError, IndexError):
#             is_verified = False

#         if not is_verified:
#             raise HTTPException(status_code=400, detail="Cannot verify validator")

#     async def validate_store_request(self, request: Request):
#         body = await request.json()

#         # Ensure required fields are in the request body
#         if  not all(field in body for field in ["uid", "nonce", "signature"]):
#             raise HTTPException(status_code=400, detail="Missing required fields in request")

#         try:
#             # Perform the nonce (timestamp) check
#             received_time_ns, current_time_ns = self._timestamp_check(received_time_ns=body["nonce"])
#             validator_uid = body["uid"]
#             # Check if nonce is already used
#             with self.store_nonce_lock:
#                 if validator_uid in self.store_used_nonces and received_time_ns in self.store_used_nonces[validator_uid]:
#                     raise HTTPException(status_code=400, detail="Replay attack detected")

#                 # Store nonce as used with expiration
#                 self.store_used_nonces[validator_uid][received_time_ns] = current_time_ns

#             # Clean up expired nonces to prevent memory bloat
#             with self.store_nonce_lock:
#                 for uid, nonces in list(self.store_used_nonces.items()):
#                     self.store_used_nonces[uid] = {
#                         ts: time_ns
#                         for ts, time_ns in nonces.items()
#                         if (current_time_ns - time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
#                     }

#             # Proceed with signature verification
#             validator_ss58_address = self.metagraph.hotkeys[validator_uid]
#             # Remove 'nonce' and 'signature' to get the original signed data structure
#             original_data = {k: v for k, v in body.items() if k not in {"nonce", "signature"}}
#             serialized_data = json.dumps(original_data, sort_keys=True, separators=(',', ':'))
#             message = f"{serialized_data}{validator_ss58_address}{body['nonce']}"
#             keypair = bt.Keypair(ss58_address=validator_ss58_address)
            
#             is_verified = keypair.verify(message, body["signature"])
#         except (ValueError, KeyError, IndexError):
#             is_verified = False

#         if not is_verified:
#             raise HTTPException(status_code=400, detail="Cannot verify validator")

class RequestValidator:
    REQUEST_EXPIRY_LIMIT_SECONDS = 5  # Expiry limit constant

    def __init__(self):
        # In-memory storage for used nonces (consider using Redis later)
        self.used_nonces = {
            "upload": defaultdict(dict),
            "store": defaultdict(dict),
        }
        self.nonce_locks = {
            "upload": threading.Lock(),
            "store": threading.Lock(),
        }

    def _timestamp_check(self, received_time_ns):
        received_time_ns = int(received_time_ns)
        current_time_ns = time.time_ns()
        time_difference_seconds = (current_time_ns - received_time_ns) / 1e9  # Convert nanoseconds to seconds

        if time_difference_seconds > self.REQUEST_EXPIRY_LIMIT_SECONDS:
            raise HTTPException(status_code=400, detail="Request expired")

        return received_time_ns, current_time_ns

    def _nonce_replay_check(self, nonce, uid, endpoint):
        """Check for replay attacks and clean up expired nonces."""
        current_time_ns = time.time_ns()
        lock = self.nonce_locks[endpoint]
        used_nonces = self.used_nonces[endpoint]

        with lock:
            if uid in used_nonces and nonce in used_nonces[uid]:
                raise HTTPException(status_code=400, detail="Replay attack detected")
            # Store the nonce
            used_nonces[uid][nonce] = current_time_ns

            # Clean up expired nonces
            for validator_uid, nonces in list(used_nonces.items()):
                used_nonces[validator_uid] = {
                    ts: ts_time_ns
                    for ts, ts_time_ns in nonces.items()
                    if (current_time_ns - ts_time_ns) / 1e9 <= self.REQUEST_EXPIRY_LIMIT_SECONDS
                }

    def _verify_signature(self, body, serialized_data, validator_uid, endpoint):
        """Verify the signature."""
        validator_ss58_address = self.metagraph.hotkeys[validator_uid]
        message = f"{serialized_data}{validator_ss58_address}{body['nonce']}"
        keypair = bt.Keypair(ss58_address=validator_ss58_address)
        return keypair.verify(message, body["signature"])

    async def _validate_request(self, request: Request, endpoint: str, required_fields: list, uid_field: str):
        """Common validation logic for all endpoints."""
        body = await request.json()

        # Check if the "signature" is present in the body
        if "signature" not in body:
            # If no signature is present, skip signature validation and return immediately
            # This assumes the request is valid, but only for backward compatibility.
            # TODO: Remove this logic once all users are updated to the latest version and are signing their requests.
            return  # Immediately return, skipping the rest of the validation

        # Ensure required fields are in the request body, supporting nested fields
        for field in required_fields:
            try:
                # Try to access the field, possibly nested
                _ = self._get_nested_data(body, field)
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Missing required field '{field}' in request")

        try:
            # Extract UID using the potentially nested field path
            validator_uid = self._get_nested_data(body, uid_field)

            # Perform the nonce (timestamp) check
            received_time_ns, _ = self._timestamp_check(received_time_ns=body["nonce"])
            self._nonce_replay_check(received_time_ns, validator_uid, endpoint)

            # Remove 'nonce' and 'signature' to get the original signed data structure
            original_data = {k: v for k, v in body.items() if k not in {"nonce", "signature"}}
            serialized_data = json.dumps(original_data, sort_keys=True, separators=(',', ':'))

            # Verify the signature
            is_verified = self._verify_signature(body, serialized_data, validator_uid, endpoint)
        except (ValueError, KeyError, IndexError):
            is_verified = False

        if not is_verified:
            raise HTTPException(status_code=400, detail="Cannot verify validator")


    async def validate_upload_request(self, request: Request):
        """Validate upload request."""
        await self._validate_request(
            request=request,
            endpoint="upload",
            required_fields=["nonce", "signature", "metadata.validator_uid"],
            uid_field="metadata.validator_uid",
        )

    async def validate_store_request(self, request: Request):
        """Validate store request."""
        await self._validate_request(
            request=request,
            endpoint="store",
            required_fields=["nonce", "signature", "uid"],
            uid_field="uid",
        )

    def _get_nested_data(self, data, key_path):
        """Retrieve nested data using a dot-separated key path."""
        keys = key_path.split('.')
        for key in keys:
            if key in data:
                data = data[key]
            else:
                raise KeyError(f"Key '{key}' not found in provided data.")
        return data

# Dependency instance
request_validator = RequestValidator()