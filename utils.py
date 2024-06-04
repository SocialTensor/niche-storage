import httpx
import time
from PIL import Image
import asyncio
import io

async def fetch_GoJourney(task_id):
    endpoint = "https://api.midjourneyapi.xyz/mj/v2/fetch"
    data = {"task_id": task_id}
    async with httpx.AsyncClient() as client:
        response = await client.post(endpoint, json=data, timeout=6)
    return response.json()

def load_image_from_url(url):
    response = httpx.get(url)
    return Image.open(io.BytesIO(response.content))

async def get_gojourney_item(output):
    task_id = output["task_id"]
    task_response = await fetch_GoJourney(task_id)
    task_status = task_response["status"]
    if task_status == "failed":
        return
    start_time = time.time()
    while True:
        task_response = await fetch_GoJourney(task_id)
        print(f"Task id: {task_id}, status: {task_response['status']}", flush=True)
        if task_response["status"] == "finished":
            img_url = task_response["task_result"]["image_url"]
            break
        await asyncio.sleep(3)
        if time.time() - start_time > 180:
            return
    image = load_image_from_url(img_url)
    return image

def base64_to_pil_image(base64_image:str):
    decoded_image = base64.b64decode(base64_image)
    image_buffer = io.BytesIO(decoded_image)
    return Image.open(image_buffer)