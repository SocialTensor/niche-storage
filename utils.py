import httpx
import time
from PIL import Image
import asyncio
import io

def fetch_GoJourney(task_id):
    endpoint = "https://api.midjourneyapi.xyz/mj/v2/fetch"
    data = {"task_id": task_id}
    response = httpx.post(endpoint, json=data, timeout=3)
    return response.json()

def load_image_from_url(url):
    response = httpx.get(url)
    return Image.open(io.BytesIO(response.content))

def get_gojourney_item(output):
    task_id = output["task_id"]
    task_response = fetch_GoJourney(task_id)
    task_status = task_response["status"]
    if task_status == "failed":
        return
    start_time = time.time()
    while True:
        task_response = fetch_GoJourney(task_id)
        if task_response["status"] == "finished":
            img_url = task_response["task_result"]["image_url"]
            break
        asyncio.sleep(3)
        if time.time() - start_time > 180:
            return
    image = load_image_from_url(img_url)
    return image