import base64
import io
import json
import os
import random
import string
from tkinter import Image
from PIL import PngImagePlugin, Image
import aiohttp
import numpy as np
from server import PromptServer
import folder_paths
from aiohttp import web
from . import ws

FILENAME_FORMAT_INIT_PREFIX = 'ProjectorInitBlob_{0}_'
FILENAME_FORMAT_CONTROLNET_PREFIX = 'ProjectorControlnetBlob_{0}_'
FILENAME_FORMAT_OUTPUT_PREFIX = 'ProjectorOutputBlob_{0}_'
FILENAME_FORMAT_INIT_PREFIX_DEFAULT = FILENAME_FORMAT_INIT_PREFIX.format("0")
FILENAME_FORMAT_CONTROLNET_PREFIX_DEFAULT = FILENAME_FORMAT_CONTROLNET_PREFIX.format("0")
FILENAME_FORMAT_OUTPUT_PREFIX_DEFAULT = FILENAME_FORMAT_OUTPUT_PREFIX.format("0")

CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))

json_cache = {}
def get_json_response(file_name):
    data = None
    if file_name in json_cache:
        data = json_cache[file_name]
    else:
        with open(os.path.join(CURRENT_PATH, file_name)) as f:
            data = json.load(f)
        json_cache[file_name] = data
    return web.Response(body=json.dumps(data), content_type='application/json')

@PromptServer.instance.routes.get('/internal/sysinfo')
async def sysinfo_handler(request):
    return get_json_response('sysinfo.json')

@PromptServer.instance.routes.get('/internal/ping')
async def ping_handler(request):
    return web.Response()

@PromptServer.instance.routes.get('/sdapi/v1/interrupt')
async def interrupt_handler(request):
    return web.Response()

@PromptServer.instance.routes.get('/sdapi/v1/options')
async def options_handler(request):
    return get_json_response('options.json')

@PromptServer.instance.routes.post('/sdapi/v1/options')
async def options_post_handler(request):
    if json_cache.get('options.json', None) is None:
        return web.Response()
    new_data = await request.json()
    json_cache['options.json'].update(new_data)
    return web.Response()

@PromptServer.instance.routes.get('/sdapi/v1/samplers')
async def samplers_handler(request):
    return get_json_response('samplers.json')

@PromptServer.instance.routes.get('/sdapi/v1/sd-models')
async def sd_models_handler(request):
    return get_json_response('sd-models.json')

@PromptServer.instance.routes.get('/sdapi/v1/upscalers')
async def upscalers_handler(request):
    return get_json_response('upscalers.json')

@PromptServer.instance.routes.get('/sdapi/v1/sd-vae')
async def sd_vae_handler(request):
    return get_json_response('sd-vae.json')

@PromptServer.instance.routes.get('/controlnet/model_list')
async def controlnet_model_list_handler(request):
    return get_json_response('controlnet_model_list.json')

@PromptServer.instance.routes.get('/controlnet/module_list')
async def controlnet_module_list_handler(request):
    return get_json_response('controlnet_module_list.json')

@PromptServer.instance.routes.post('/sdapi/v1/txt2img')
async def txt2img_handler(request):
    json_data = await request.json()
    randdom_id = "".join(random.choice(string.ascii_letters) for i in range(10))
    image_bytes_list, image_mask_bytes_list = get_controlnet_image_list(json_data)
    await upload_image_list(image_bytes_list, FILENAME_FORMAT_CONTROLNET_PREFIX.format(randdom_id) + "{}.png")
    await upload_image_list(image_mask_bytes_list, FILENAME_FORMAT_CONTROLNET_PREFIX.format(randdom_id) + "{}_mask.png")
    await ws.run_prompt(randdom_id)
    images = await find_output_image_to_b64(FILENAME_FORMAT_OUTPUT_PREFIX.format(randdom_id))
    return web.Response(body=json.dumps({'images': images}), content_type='application/json')

@PromptServer.instance.routes.post('/sdapi/v1/img2img')
async def img2img_handler(request):
    json_data = await request.json()
    random_id = "".join(random.choice(string.ascii_letters) for i in range(10))
    init_image_list = get_init_image_list(json_data)
    await upload_image_list(init_image_list, FILENAME_FORMAT_INIT_PREFIX.format(random_id) + "{}.png")
    init_mask_list = get_init_image_mask_list(json_data)
    await upload_image_list(init_mask_list, FILENAME_FORMAT_INIT_PREFIX.format(random_id) + "{}_mask.png")
    image_bytes_list, image_mask_bytes_list = get_controlnet_image_list(json_data)
    await upload_image_list(image_bytes_list, FILENAME_FORMAT_CONTROLNET_PREFIX.format(random_id) + "{}.png")
    await upload_image_list(image_mask_bytes_list, FILENAME_FORMAT_CONTROLNET_PREFIX.format(random_id) + "{}_mask.png")
    await ws.run_prompt(random_id)
    images = await find_output_image_to_b64(FILENAME_FORMAT_OUTPUT_PREFIX.format(random_id))
    return web.Response(body=json.dumps({'images': images}), content_type='application/json')

@PromptServer.instance.routes.post('/sdapi/v1/progress')
async def progress_handler(request):
    json_data = await request.json()
    return web.Response()

async def upload_image_list(image_bytes_list, name_index_template):
    if isinstance(image_bytes_list, str):
        image_bytes_list = [image_bytes_list]
    if not image_bytes_list or len(image_bytes_list) <= 0:
        return
    for index in range(len(image_bytes_list)):
        image_bytes = image_bytes_list[index]
        form = aiohttp.FormData()
        filename = name_index_template.format(index)
        form.add_field('image', image_bytes, filename=filename, content_type='image/png')
        form.add_field('overwrite', 'true')
        async with aiohttp.ClientSession() as session:
            await session.post('http://localhost:8188/upload/image', data = form)

async def find_output_image_to_b64(output_prefix):
    images = []
    output_dir = folder_paths.get_output_directory()
    output_files = [f for f in os.listdir(output_dir) if f.startswith(output_prefix)]
    output_files.sort()
    if len(output_files) <= 0:
        return images
    for output_file in output_files:
        with open(os.path.join(output_dir, output_file), 'rb') as f:
            output_bytes = f.read()
            image = Image.open(io.BytesIO(output_bytes))
            images.append(encode_pil_to_base64(image))
    return images

def get_init_image_mask_list(json_data):
    mask_bytes_list = []
    init_mask = json_data.get('mask', None)
    if init_mask is None:
        return mask_bytes_list
    mask_bytes = base64.b64decode(init_mask)
    mask_bytes_list.append(mask_bytes)
    return mask_bytes_list

def get_init_image_list(json_data):
    image_bytes_list = []
    init_images = json_data.get('init_images', None)
    if init_images is None:
        return image_bytes_list
    for image in init_images:
        image_bytes = base64.b64decode(image)
        image_bytes_list.append(image_bytes)
    return image_bytes_list

def get_controlnet_mask_list(json_data):
    alwayson_scripts = json_data.get('alwayson_scripts', None)
    if alwayson_scripts is None:
        return []
    controlnet = alwayson_scripts.get('controlnet', None)
    if controlnet is None:
        return []
    args = controlnet.get('args', None)
    if args is None:
        return []
    if len(args) <= 0:
        return []
    mask_bytes_list = []
    for arg in args:
        mask_b64 = arg.get('image_mask', None)
        if mask_b64 is None:
            mask_bytes_list.append(None)
            continue
        mask_bytes = base64.b64decode(mask_b64)
        mask_bytes_list.append(mask_bytes)
    return mask_bytes_list

def get_controlnet_image_list(json_data):
    alwayson_scripts = json_data.get('alwayson_scripts', None)
    if alwayson_scripts is None:
        return []
    controlnet = alwayson_scripts.get('controlnet', None)
    if controlnet is None:
        return []
    args = controlnet.get('args', None)
    if args is None:
        return []
    if len(args) <= 0:
        return []
    image_bytes_list = []
    for arg in args:
        image_b64 = arg.get('image', None)
        if image_b64 is None:
            image_bytes_list.append(None)
            continue
        image_bytes = base64.b64decode(image_b64)
        image_bytes_list.append(image_bytes)
    image_mask_bytes_list = []
    for arg in args:
        image_mask_b64 = arg.get('image_mask', None)
        if image_mask_b64 is None:
            image_mask_bytes_list.append(None)
            continue
        image_mask_bytes = base64.b64decode(image_mask_b64)
        image_mask_bytes_list.append(image_mask_bytes)
    return image_bytes_list, image_mask_bytes_list

def encode_pil_to_base64(image):
    with io.BytesIO() as output_bytes:
        if isinstance(image, str):
            return image
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image)
        use_metadata = False
        metadata = PngImagePlugin.PngInfo()
        for key, value in image.info.items():
            if isinstance(key, str) and isinstance(value, str):
                metadata.add_text(key, value)
                use_metadata = True
        image.save(output_bytes, format="PNG", pnginfo=(metadata if use_metadata else None), quality=100)
        bytes_data = output_bytes.getvalue()
    return base64.b64encode(bytes_data).decode('ascii')