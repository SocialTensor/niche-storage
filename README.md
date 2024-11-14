# Request Validation Logic

The validation process ensures requests are authentic, timely, and secure, structured around verifying field presence, preventing replay attacks, and confirming the request’s authenticity.

## Core Validation Steps

1. **Field Presence Check (Flexible)**
   - Verify that essential fields (such as `metadata`, `nonce`, `signature`) are present.
   - Required fields may vary by endpoint, so validation is adaptable to include additional fields as needed.

2. **Nonce Expiry Validation**
   - Check if the `nonce` (timestamp) is within the acceptable limit (`REQUEST_EXPIRY_LIMIT_SECONDS`).
   - Requests exceeding this time limit are marked expired and rejected.

3. **Replay Attack Prevention**
   - Detect and reject requests with reused `nonce` values for a given `validator_uid` to prevent replay attacks.
   - Nonces are stored temporarily and periodically cleaned to maintain efficiency.

4. **Signature Verification**
   - Construct the original message from request data and use the validator’s public key to verify the `signature`.
   - Only verified signatures are processed; invalid ones are rejected.

5. **Error Handling**
   - Each validation failure returns a clear error message, identifying issues like missing fields, expired requests, replay detection, or invalid signatures.

This approach provides a secure, adaptable validation flow, supporting different endpoints with tailored field checks and comprehensive verification.
